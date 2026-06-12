package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"
)

// ---------------------------------------------------------------------------
// D4 — Path-confusion guard.
//
// The original code rewrote the upstream path when ``originalPath`` started
// with ``/mcp`` regardless of whether the route's target path was
// ``/mcp``-rooted. A route with target ``http://internal.svc/api/v1`` would
// happily forward a caller-supplied ``/mcp/users`` to
// ``http://internal.svc/api/v1/users``. We now scope the rewrite to routes
// whose target path is *itself* rooted under ``/mcp``.
// ---------------------------------------------------------------------------

// isMCPRootedPath returns true when *p* is an MCP-style path root
// (specifically "/mcp" with or without a trailing slash). This is the
// only target path for which the caller-supplied ``/mcp/...`` rewrite
// is safe.
func isMCPRootedPath(p string) bool {
	cleaned := strings.TrimSuffix(p, "/")
	return cleaned == "/mcp"
}

// ---------------------------------------------------------------------------
// D5 — Timing-safe bearer comparison.
// ---------------------------------------------------------------------------

// safeEqualBearer compares two ``Authorization: Bearer <secret>`` strings in
// constant time. Returning a plain ``==`` is vulnerable to remote timing
// attacks (see the OWASP JWT cheat sheet).
func safeEqualBearer(a, b string) bool {
	// Both inputs include the "Bearer " prefix. Use
	// crypto/subtle.ConstantTimeCompare on the underlying bytes after
	// length-equalizing to avoid leaking prefix-length differences.
	if len(a) != len(b) {
		// Compare the longer against the shorter padded with NULs so
		// the comparison runs in constant time regardless.
		if len(a) < len(b) {
			padded := a + strings.Repeat("\x00", len(b)-len(a))
			subtle.ConstantTimeCompare([]byte(padded), []byte(b))
			return false
		}
		padded := b + strings.Repeat("\x00", len(a)-len(b))
		subtle.ConstantTimeCompare([]byte(a), []byte(padded))
		return false
	}
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}

// hopByHopHeaders is the set of headers that must NOT be forwarded by a
// proxy (RFC 7230 §6.1). Stripping these prevents a downstream
// service from trusting client-supplied values that should be re-derived.
var hopByHopHeaders = []string{
	"Connection",
	"Keep-Alive",
	"Proxy-Authenticate",
	"Proxy-Authorization", // D6 — auth leakage via Proxy-Authorization
	"TE",
	"Trailer",
	"Transfer-Encoding",
	"Upgrade",
	"X-Forwarded-For",      // D6 — spoofed-client-IP injection
	"X-Forwarded-Host",     // D6 — host-header injection
	"X-Forwarded-Proto",    // D6 — protocol-spoofing
	"X-Forwarded-For-Proto",
	"X-Real-IP",            // D6 — spoofed source IP
	"Forwarded",            // RFC 7239
	"True-Client-IP",       // D6
	"CF-Connecting-IP",     // D6 — Cloudflare spoofed source
	"X-Client-IP",
	"X-Originating-IP",
}

func sanitizeForwardedHeaders(req *http.Request) {
	for _, h := range hopByHopHeaders {
		req.Header.Del(h)
	}
}

type AuthMode string

const (
	AuthModeBearer   AuthMode = "bearer"
	AuthModeHeader   AuthMode = "header"
	AuthModeValidate AuthMode = "validate"
	AuthModeNone     AuthMode = "none"
)

type Route struct {
	Listen       string   `json:"listen"`
	Target       string   `json:"target"`
	Auth         AuthMode `json:"auth"`
	SecretEnv    string   `json:"secret_env"`
	HeaderName   string   `json:"header_name"`
	HeaderPrefix string   `json:"header_prefix"`
}

type Proxy struct {
	routes  []Route
	secrets map[string]string
	servers []*http.Server
	logger  *slog.Logger
}

func NewProxy(routes []Route, logger *slog.Logger) *Proxy {
	secrets := make(map[string]string)
	for _, r := range routes {
		if r.SecretEnv != "" {
			if v := os.Getenv(r.SecretEnv); v != "" {
				secrets[r.SecretEnv] = v
			}
		}
	}
	return &Proxy{
		routes:  routes,
		secrets: secrets,
		logger:  logger,
	}
}

func (p *Proxy) Start() error {
	var wg sync.WaitGroup
	for _, route := range p.routes {
		target, err := url.Parse(route.Target)
		if err != nil {
			return fmt.Errorf("invalid target URL %q: %w", route.Target, err)
		}

		proxy := httputil.NewSingleHostReverseProxy(target)
		proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			p.logger.Error("proxy error", "route", route.Listen, "target", route.Target, "error", err)
			http.Error(w, "proxy error", http.StatusBadGateway)
		}

		originalDirector := proxy.Director
		proxy.Director = func(req *http.Request) {
			originalPath := req.URL.Path
			originalDirector(req)
			// D4 — Path-confusion guard. Only rewrite the upstream path
			// when the target's own path is rooted at ``/mcp``.
			// Otherwise a caller-supplied ``/mcp/...`` path would be
			// silently rewritten with an attacker-controlled prefix.
			if isMCPRootedPath(target.Path) && strings.HasPrefix(originalPath, "/mcp") {
				suffix := strings.TrimPrefix(originalPath, "/mcp")
				req.URL.Path = joinURLPath(target.Path, suffix)
				req.URL.RawPath = target.EscapedPath()
			}
			// D6 — strip hop-by-hop and forwarded-* headers so the
			// downstream service can't be tricked by client-supplied
			// X-Forwarded-For / True-Client-IP / Proxy-Authorization
			// values.
			sanitizeForwardedHeaders(req)
			// Set the Host header to match the target host (required by some APIs like GitHub Copilot)
			req.Host = target.Host
			p.injectAuth(req, route)
			// Ensure User-Agent is set for APIs that require it, but
			// only when the client did not set their own. Do not
			// clobber a legitimate caller UA.
			if req.Header.Get("User-Agent") == "" {
				req.Header.Set("User-Agent", "kubesynapse-credential-proxy/1.0")
			}
		}

		var handler http.Handler
		switch route.Auth {
		case AuthModeValidate:
			handler = p.validateMiddleware(proxy, route)
		default:
			handler = proxy
		}

		srv := &http.Server{
			Addr:              route.Listen,
			Handler:           handler,
			ReadHeaderTimeout: 10 * time.Second,
			ReadTimeout:       30 * time.Second,
			WriteTimeout:      300 * time.Second,
			IdleTimeout:       60 * time.Second,
		}
		p.servers = append(p.servers, srv)

		wg.Add(1)
		go func(s *http.Server, r Route) {
			defer wg.Done()
			p.logger.Info("starting route", "listen", r.Listen, "target", r.Target, "auth", r.Auth)
			if err := s.ListenAndServe(); err != nil && err != http.ErrServerClosed {
				p.logger.Error("server error", "listen", r.Listen, "error", err)
			}
		}(srv, route)
	}

	wg.Wait()
	return nil
}

func (p *Proxy) Shutdown(ctx context.Context) {
	for _, srv := range p.servers {
		if err := srv.Shutdown(ctx); err != nil {
			p.logger.Error("shutdown error", "error", err)
		}
	}
}

func (p *Proxy) injectAuth(req *http.Request, route Route) {
	secret := p.secrets[route.SecretEnv]
	if secret == "" {
		return
	}

	switch route.Auth {
	case AuthModeBearer:
		req.Header.Set("Authorization", "Bearer "+secret)
	case AuthModeHeader:
		headerName := route.HeaderName
		if headerName == "" {
			headerName = "Authorization"
		}
		req.Header.Set(headerName, route.HeaderPrefix+secret)
	}
}

func (p *Proxy) validateMiddleware(next http.Handler, route Route) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		secret := p.secrets[route.SecretEnv]
		if secret == "" {
			next.ServeHTTP(w, r)
			return
		}

		auth := r.Header.Get("Authorization")
		expected := "Bearer " + secret
		// D5 — timing-safe comparison. Plain ``!=`` leaks the position
		// of the first byte mismatch via response latency.
		if !safeEqualBearer(auth, expected) {
			p.logger.Warn("invalid auth", "route", route.Listen, "remote", r.RemoteAddr)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}

		r.Header.Del("Authorization")
		next.ServeHTTP(w, r)
	})
}

func loadRoutes() ([]Route, error) {
	raw := os.Getenv("PROXY_ROUTES")
	if raw == "" {
		return nil, fmt.Errorf("PROXY_ROUTES environment variable is required")
	}

	var routes []Route
	if err := json.Unmarshal([]byte(raw), &routes); err != nil {
		return nil, fmt.Errorf("failed to parse PROXY_ROUTES: %w", err)
	}

	for i := range routes {
		routes[i].Listen = strings.TrimSpace(routes[i].Listen)
		routes[i].Target = strings.TrimSpace(routes[i].Target)
		routes[i].SecretEnv = strings.TrimSpace(routes[i].SecretEnv)
		routes[i].HeaderName = strings.TrimSpace(routes[i].HeaderName)
		routes[i].HeaderPrefix = routeStrOrEmpty(routes[i].HeaderPrefix)
		if routes[i].Auth == "" {
			routes[i].Auth = AuthModeNone
		}
	}

	return routes, nil
}

func routeStrOrEmpty(value string) string {
	return value
}

func joinURLPath(base string, suffix string) string {
	base = strings.TrimSuffix(base, "/")
	if suffix == "" || suffix == "/" {
		if base == "" {
			return "/"
		}
		return base
	}
	if !strings.HasPrefix(suffix, "/") {
		suffix = "/" + suffix
	}
	if base == "" {
		return suffix
	}
	return base + suffix
}

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))

	routes, err := loadRoutes()
	if err != nil {
		logger.Error("failed to load routes", "error", err)
		os.Exit(1)
	}

	proxy := NewProxy(routes, logger)

	healthMux := http.NewServeMux()
	healthMux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	})
	healthSrv := &http.Server{
		Addr:              ":9090",
		Handler:           healthMux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		logger.Info("starting health server", "addr", ":9090")
		if err := healthSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("health server error", "error", err)
		}
	}()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)

	go func() {
		<-sigCh
		logger.Info("shutdown signal received")
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		proxy.Shutdown(ctx)
		healthSrv.Shutdown(ctx)
	}()

	if err := proxy.Start(); err != nil {
		logger.Error("proxy failed", "error", err)
		os.Exit(1)
	}
}
