package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// ---------------------------------------------------------------------------
// WP-7: Tunable connection-pool and timeout configuration
// ---------------------------------------------------------------------------

// proxyTransportConfig holds the pooled Transport shared across all routes.
// Using a shared Transport allows connections to be reused across forward
// requests to the same upstream, which reduces TIME_WAIT socket accumulation
// under high parallel load.
var _sharedTransport *http.Transport

func init() {
	_sharedTransport = buildTransport()
}

func envInt(name string, fallback int) int {
	if v := os.Getenv(name); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return fallback
}

func envDuration(name string, fallback time.Duration) time.Duration {
	if v := os.Getenv(name); v != "" {
		if d, err := time.ParseDuration(v); err == nil && d > 0 {
			return d
		}
	}
	return fallback
}

func buildTransport() *http.Transport {
	return &http.Transport{
		// WP-7: raise idle-connection ceilings from Go's default of 100/2.
		MaxIdleConns:        envInt("PROXY_TRANSPORT_MAX_IDLE_CONNS", 200),
		MaxIdleConnsPerHost: envInt("PROXY_TRANSPORT_MAX_IDLE_CONNS_PER_HOST", 100),
		MaxConnsPerHost:     envInt("PROXY_TRANSPORT_MAX_CONNS_PER_HOST", 0), // 0 = unlimited
		IdleConnTimeout:     envDuration("PROXY_TRANSPORT_IDLE_CONN_TIMEOUT", 90*time.Second),
		// WP-4/WP-7: prefer HTTP/2 for multiplexed concurrent requests.
		ForceAttemptHTTP2: true,
		DialContext: (&net.Dialer{
			Timeout:   envDuration("PROXY_DIAL_TIMEOUT", 10*time.Second),
			KeepAlive: envDuration("PROXY_DIAL_KEEPALIVE", 30*time.Second),
		}).DialContext,
		TLSHandshakeTimeout:   envDuration("PROXY_TLS_HANDSHAKE_TIMEOUT", 10*time.Second),
		ResponseHeaderTimeout: envDuration("PROXY_RESPONSE_HEADER_TIMEOUT", 30*time.Second),
		ExpectContinueTimeout: 1 * time.Second,
	}
}

// streamWriteTimeout returns the WriteTimeout to use for a route that carries
// long-running SSE streams.  Defaults to 0 (unlimited) so that the runtime's
// own LIVE_UPDATE_MAX_WALL_SECONDS (~900 s) governs the upper bound, not this
// proxy layer.  Override via PROXY_STREAM_WRITE_TIMEOUT_SECONDS (e.g. "960").
//
// WP-4: The previous hard-coded 300 s truncated streaming turns at 5 min.
func streamWriteTimeout() time.Duration {
	if v := os.Getenv("PROXY_STREAM_WRITE_TIMEOUT_SECONDS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			if n <= 0 {
				return 0 // explicit unlimited
			}
			return time.Duration(n) * time.Second
		}
	}
	return 0 // default: unlimited (let the runtime control the wall-clock cap)
}

// isStreamingRoute returns true when the route is the inbound gateway→agent
// port (AuthModeValidate) or carries SSE traffic.  These need an unlimited
// WriteTimeout so long-running turns are not truncated.
func isStreamingRoute(route Route) bool {
	return route.Auth == AuthModeValidate
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

		// WP-7: inject the shared pooled Transport so connections are reused.
		proxy := httputil.NewSingleHostReverseProxy(target)
		proxy.Transport = _sharedTransport
		proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			p.logger.Error("proxy error", "route", route.Listen, "target", route.Target, "error", err)
			http.Error(w, "proxy error", http.StatusBadGateway)
		}

		originalDirector := proxy.Director
		proxy.Director = func(req *http.Request) {
			originalPath := req.URL.Path
			originalDirector(req)
			// Preserve the upstream endpoint path when the target already includes a
			// concrete route such as /mcp. Otherwise local proxy requests to /mcp get
			// forwarded as /mcp/mcp and remote MCP servers return 404.
			if target.Path != "" && target.Path != "/" && strings.HasPrefix(originalPath, "/mcp") {
				suffix := strings.TrimPrefix(originalPath, "/mcp")
				req.URL.Path = joinURLPath(target.Path, suffix)
				req.URL.RawPath = target.EscapedPath()
			}
			// Set the Host header to match the target host (required by some APIs like GitHub Copilot)
			req.Host = target.Host
			p.injectAuth(req, route)
			// Ensure User-Agent is set for APIs that require it
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

		// WP-4: streaming/inbound routes use an unlimited WriteTimeout so that
		// long-running SSE turns (up to ~900 s in the runtime) are not cut off
		// by the proxy at the previous hard-coded 300 s.
		writeTimeout := time.Duration(300) * time.Second
		if isStreamingRoute(route) {
			writeTimeout = streamWriteTimeout()
		}
		srv := &http.Server{
			Addr:              route.Listen,
			Handler:           handler,
			ReadHeaderTimeout: 10 * time.Second,
			ReadTimeout:       0, // streaming responses read continuously
			WriteTimeout:      writeTimeout,
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
		if auth != expected {
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
