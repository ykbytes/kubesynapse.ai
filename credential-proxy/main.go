package main

import (
	"context"
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
			originalDirector(req)
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
