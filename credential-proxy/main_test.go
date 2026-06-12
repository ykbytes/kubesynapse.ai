package main

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

func TestInjectAuthBearer(t *testing.T) {
	os.Setenv("TEST_SECRET", "my-secret-key")
	defer os.Unsetenv("TEST_SECRET")

	routes := []Route{
		{Listen: ":0", Target: "http://localhost:9999", Auth: AuthModeBearer, SecretEnv: "TEST_SECRET"},
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	proxy := NewProxy(routes, logger)

	req := httptest.NewRequest("GET", "/test", nil)
	proxy.injectAuth(req, routes[0])

	if got := req.Header.Get("Authorization"); got != "Bearer my-secret-key" {
		t.Errorf("expected 'Bearer my-secret-key', got %q", got)
	}
}

func TestInjectAuthHeader(t *testing.T) {
	os.Setenv("TEST_API_KEY", "ctx7sk-abc123")
	defer os.Unsetenv("TEST_API_KEY")

	routes := []Route{
		{Listen: ":0", Target: "http://localhost:9999", Auth: AuthModeHeader, SecretEnv: "TEST_API_KEY", HeaderName: "X-API-Key"},
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	proxy := NewProxy(routes, logger)

	req := httptest.NewRequest("GET", "/test", nil)
	proxy.injectAuth(req, routes[0])

	if got := req.Header.Get("X-API-Key"); got != "ctx7sk-abc123" {
		t.Errorf("expected 'ctx7sk-abc123', got %q", got)
	}
}

func TestInjectAuthEmptySecret(t *testing.T) {
	routes := []Route{
		{Listen: ":0", Target: "http://localhost:9999", Auth: AuthModeBearer, SecretEnv: "NONEXISTENT"},
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	proxy := NewProxy(routes, logger)

	req := httptest.NewRequest("GET", "/test", nil)
	proxy.injectAuth(req, routes[0])

	if got := req.Header.Get("Authorization"); got != "" {
		t.Errorf("expected empty Authorization, got %q", got)
	}
}

func TestValidateMiddlewareValid(t *testing.T) {
	os.Setenv("TEST_PASSWORD", "server-pass-123")
	defer os.Unsetenv("TEST_PASSWORD")

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			t.Error("Authorization header should be stripped")
		}
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	}))
	defer backend.Close()

	routes := []Route{
		{Listen: ":0", Target: backend.URL, Auth: AuthModeValidate, SecretEnv: "TEST_PASSWORD"},
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	proxy := NewProxy(routes, logger)

	handler := proxy.validateMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}), routes[0])

	req := httptest.NewRequest("GET", "/test", nil)
	req.Header.Set("Authorization", "Bearer server-pass-123")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", rec.Code)
	}
}

func TestValidateMiddlewareInvalid(t *testing.T) {
	os.Setenv("TEST_PASSWORD", "server-pass-123")
	defer os.Unsetenv("TEST_PASSWORD")

	routes := []Route{
		{Listen: ":0", Target: "http://localhost:9999", Auth: AuthModeValidate, SecretEnv: "TEST_PASSWORD"},
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	proxy := NewProxy(routes, logger)

	handler := proxy.validateMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}), routes[0])

	req := httptest.NewRequest("GET", "/test", nil)
	req.Header.Set("Authorization", "Bearer wrong-password")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("expected 401, got %d", rec.Code)
	}
}

func TestValidateMiddlewareNoSecret(t *testing.T) {
	routes := []Route{
		{Listen: ":0", Target: "http://localhost:9999", Auth: AuthModeValidate, SecretEnv: "NONEXISTENT"},
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	proxy := NewProxy(routes, logger)

	handler := proxy.validateMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}), routes[0])

	req := httptest.NewRequest("GET", "/test", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("expected 200 when no secret configured, got %d", rec.Code)
	}
}

func TestLoadRoutes(t *testing.T) {
	routes := []Route{
		{Listen: ":4001", Target: "http://litellm:4000", Auth: AuthModeBearer, SecretEnv: "LITELLM_KEY"},
		{Listen: ":4010", Target: "http://mcp-hub:8000", Auth: AuthModeBearer, SecretEnv: "MCP_TOKEN"},
	}
	data, _ := json.Marshal(routes)
	os.Setenv("PROXY_ROUTES", string(data))
	defer os.Unsetenv("PROXY_ROUTES")

	loaded, err := loadRoutes()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(loaded) != 2 {
		t.Fatalf("expected 2 routes, got %d", len(loaded))
	}
	if loaded[0].Listen != ":4001" {
		t.Errorf("expected :4001, got %s", loaded[0].Listen)
	}
}

func TestLoadRoutesEmpty(t *testing.T) {
	os.Unsetenv("PROXY_ROUTES")
	_, err := loadRoutes()
	if err == nil {
		t.Error("expected error for empty PROXY_ROUTES")
	}
}

func TestLoadRoutesInvalidJSON(t *testing.T) {
	os.Setenv("PROXY_ROUTES", "not-json")
	defer os.Unsetenv("PROXY_ROUTES")
	_, err := loadRoutes()
	if err == nil {
		t.Error("expected error for invalid JSON")
	}
}

func TestEndToEndBearerProxy(t *testing.T) {
	os.Setenv("E2E_SECRET", "test-bearer-token")
	defer os.Unsetenv("E2E_SECRET")

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth := r.Header.Get("Authorization")
		if auth != "Bearer test-bearer-token" {
			t.Errorf("backend expected 'Bearer test-bearer-token', got %q", auth)
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("success"))
	}))
	defer backend.Close()

	routes := []Route{
		{Listen: ":0", Target: backend.URL, Auth: AuthModeBearer, SecretEnv: "E2E_SECRET"},
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	proxy := NewProxy(routes, logger)

	target, _ := url.Parse(backend.URL)
	reverseProxy := httputil.NewSingleHostReverseProxy(target)
	originalDirector := reverseProxy.Director
	reverseProxy.Director = func(req *http.Request) {
		originalDirector(req)
		proxy.injectAuth(req, routes[0])
	}

	testSrv := httptest.NewServer(reverseProxy)
	defer testSrv.Close()

	resp, err := http.Get(testSrv.URL + "/test")
	if err != nil {
		t.Fatalf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200, got %d", resp.StatusCode)
	}
}

func TestProxyPreservesConcreteTargetPath(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/mcp" {
			t.Fatalf("expected upstream path /mcp, got %q", r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	}))
	defer backend.Close()

	target, err := url.Parse(backend.URL + "/mcp")
	if err != nil {
		t.Fatalf("parse target: %v", err)
	}

	proxy := httputil.NewSingleHostReverseProxy(target)
	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalPath := req.URL.Path
		originalDirector(req)
		if target.Path != "" && target.Path != "/" && strings.HasPrefix(originalPath, "/mcp") {
			suffix := strings.TrimPrefix(originalPath, "/mcp")
			req.URL.Path = joinURLPath(target.Path, suffix)
			req.URL.RawPath = target.EscapedPath()
		}
		req.Host = target.Host
	}

	server := httptest.NewServer(proxy)
	defer server.Close()

	resp, err := http.Get(server.URL + "/mcp")
	if err != nil {
		t.Fatalf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("expected 200, got %d body=%s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
}

func TestSafeEqualBearer_ExactMatch(t *testing.T) {
	if !safeEqualBearer("Bearer abc", "Bearer abc") {
		t.Error("expected equal strings to match")
	}
}

func TestSafeEqualBearer_RejectsMismatch(t *testing.T) {
	if safeEqualBearer("Bearer abc", "Bearer abd") {
		t.Error("expected mismatch to be rejected")
	}
	if safeEqualBearer("Bearer abc", "Bearer ab") {
		t.Error("expected length mismatch to be rejected")
	}
	if safeEqualBearer("Bearer", "Bearer abc") {
		t.Error("expected prefix-only match to be rejected")
	}
}

func TestIsMCPRootedPath(t *testing.T) {
	cases := map[string]bool{
		"/mcp":          true,
		"/mcp/":         true,
		"/mcp/v1":       false,
		"/api/v1":       false,
		"":              false,
		"/":             false,
		"/mcpfoo":       false,
		"/api/v1/mcp":   false,
	}
	for in, want := range cases {
		if got := isMCPRootedPath(in); got != want {
			t.Errorf("isMCPRootedPath(%q) = %v, want %v", in, got, want)
		}
	}
}

func TestSanitizeForwardedHeaders(t *testing.T) {
	req := httptest.NewRequest("GET", "/test", nil)
	req.Header.Set("X-Forwarded-For", "1.2.3.4")
	req.Header.Set("X-Forwarded-Proto", "https")
	req.Header.Set("X-Real-IP", "1.2.3.4")
	req.Header.Set("True-Client-IP", "1.2.3.4")
	req.Header.Set("CF-Connecting-IP", "1.2.3.4")
	req.Header.Set("Proxy-Authorization", "Bearer leaked")
	req.Header.Set("Forwarded", "for=1.2.3.4")
	req.Header.Set("X-Forwarded-Host", "internal.svc")
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer real")

	sanitizeForwardedHeaders(req)

	// All forwarded-* / proxy-auth / real-ip must be stripped.
	for _, h := range []string{
		"X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host",
		"X-Real-IP", "True-Client-IP", "CF-Connecting-IP",
		"Proxy-Authorization", "Forwarded",
	} {
		if got := req.Header.Get(h); got != "" {
			t.Errorf("expected %q to be stripped, got %q", h, got)
		}
	}
	// Content-Type and Authorization are NOT hop-by-hop and must survive.
	if got := req.Header.Get("Content-Type"); got != "application/json" {
		t.Errorf("expected Content-Type to survive, got %q", got)
	}
	if got := req.Header.Get("Authorization"); got != "Bearer real" {
		t.Errorf("expected Authorization to survive, got %q", got)
	}
}

func TestPathConfusionGuardRefusesNonMCPTarget(t *testing.T) {
	// D4 — a route with target=…/api/v1 must NOT rewrite a
	// caller-supplied /mcp/users path to upstream /api/v1/users.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/users" {
			t.Fatalf("upstream received /api/v1/users — path confusion confirmed")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	target, err := url.Parse(backend.URL + "/api/v1")
	if err != nil {
		t.Fatalf("parse target: %v", err)
	}

	proxy := httputil.NewSingleHostReverseProxy(target)
	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalPath := req.URL.Path
		originalDirector(req)
		if isMCPRootedPath(target.Path) && strings.HasPrefix(originalPath, "/mcp") {
			suffix := strings.TrimPrefix(originalPath, "/mcp")
			req.URL.Path = joinURLPath(target.Path, suffix)
			req.URL.RawPath = target.EscapedPath()
		}
	}

	server := httptest.NewServer(proxy)
	defer server.Close()

	resp, err := http.Get(server.URL + "/mcp/users")
	if err != nil {
		t.Fatalf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("expected 200, got %d body=%s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
}

func TestHealthEndpoint(t *testing.T) {
	healthMux := http.NewServeMux()
	healthMux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	})
	srv := httptest.NewServer(healthMux)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/healthz")
	if err != nil {
		t.Fatalf("health check failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200, got %d", resp.StatusCode)
	}

	body, _ := io.ReadAll(resp.Body)
	if string(body) != "ok" {
		t.Errorf("expected 'ok', got %q", string(body))
	}
}

func TestShutdownGraceful(t *testing.T) {
	routes := []Route{
		{Listen: ":0", Target: "http://localhost:9999", Auth: AuthModeNone},
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	proxy := NewProxy(routes, logger)

	proxy.servers = append(proxy.servers, &http.Server{Addr: ":0"})

	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	proxy.Shutdown(ctx)
}
