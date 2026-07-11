package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

const (
	modelLabel       = "llm.cogito.dev/model-config=true"
	activeModelAnno  = "llm.cogito.dev/active-model"
	switchedAtAnno   = "llm.cogito.dev/switched-at"
	defaultMaxBody   = 32 << 20
	defaultTimeout   = 30 * time.Minute
	backendProbeWait = 2 * time.Second
)

type modelConfig struct {
	ID          string
	DisplayName string
	MaxModelLen int
	Created     time.Time
	Args        []string
	Source      string
}

type registry struct {
	models map[string]modelConfig
}

type proxy struct {
	client          kubernetes.Interface
	namespace       string
	deployment      string
	container       string
	backend         *url.URL
	httpClient      *http.Client
	transitionLimit time.Duration
	maxBody         int64

	stateMu       sync.RWMutex
	registry      registry
	active        string
	transitioning bool
	ready         bool
	startedAt     time.Time
	activeSince   time.Time

	switchesTotal atomic.Uint64
	configErrors  atomic.Uint64
	lastSwitch    atomic.Int64 // nanoseconds
	lastStart     atomic.Int64 // nanoseconds
}

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	config, err := rest.InClusterConfig()
	if err != nil {
		logger.Error("load in-cluster Kubernetes config", "error", err)
		os.Exit(1)
	}
	client, err := kubernetes.NewForConfig(config)
	if err != nil {
		logger.Error("create Kubernetes client", "error", err)
		os.Exit(1)
	}
	backend, err := url.Parse(env("BACKEND_URL", "http://llm-vllm:8000"))
	if err != nil {
		logger.Error("parse BACKEND_URL", "error", err)
		os.Exit(1)
	}
	p := &proxy{
		client:          client,
		namespace:       env("POD_NAMESPACE", mustNamespace()),
		deployment:      env("VLLM_DEPLOYMENT", "llm-vllm"),
		container:       env("VLLM_CONTAINER", "vllm"),
		backend:         backend,
		httpClient:      &http.Client{Timeout: 15 * time.Second},
		transitionLimit: durationEnv("TRANSITION_TIMEOUT", defaultTimeout),
		maxBody:         int64Env("MAX_REQUEST_BODY_BYTES", defaultMaxBody),
		startedAt:       time.Now(),
	}

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	if err := p.refresh(ctx); err != nil {
		logger.Warn("initial model registry load failed; will retry", "error", err)
	}
	cancel()
	go p.watchConfigs(logger)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", p.healthz)
	mux.HandleFunc("GET /readyz", p.readyz)
	mux.HandleFunc("GET /metrics", p.metrics)
	mux.HandleFunc("GET /v1/models", p.models)
	mux.HandleFunc("GET /v1/models/{id}", p.model)
	mux.HandleFunc("/v1/", p.inference)

	server := &http.Server{
		Addr:              env("LISTEN_ADDR", ":8080"),
		Handler:           mux,
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       5 * time.Minute,
	}
	logger.Info("vLLM proxy listening", "address", server.Addr, "backend", backend.String())
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		logger.Error("serve", "error", err)
		os.Exit(1)
	}
}

func (p *proxy) watchConfigs(logger *slog.Logger) {
	for {
		watch, err := p.client.CoreV1().ConfigMaps(p.namespace).Watch(context.Background(), metav1.ListOptions{LabelSelector: modelLabel})
		if err != nil {
			p.configErrors.Add(1)
			logger.Warn("watch model ConfigMaps", "error", err)
			time.Sleep(5 * time.Second)
			continue
		}
		for range watch.ResultChan() {
			ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			if err := p.refresh(ctx); err != nil {
				p.configErrors.Add(1)
				logger.Warn("refresh model ConfigMaps", "error", err)
			}
			cancel()
		}
	}
}

func (p *proxy) refresh(ctx context.Context) error {
	items, err := p.client.CoreV1().ConfigMaps(p.namespace).List(ctx, metav1.ListOptions{LabelSelector: modelLabel})
	if err != nil {
		return err
	}
	next := registry{models: make(map[string]modelConfig, len(items.Items))}
	for _, cm := range items.Items {
		cfg, err := parseModelConfig(cm.Name, cm.Data)
		if err != nil {
			return fmt.Errorf("%s: %w", cm.Name, err)
		}
		if _, exists := next.models[cfg.ID]; exists {
			return fmt.Errorf("duplicate model_id %q", cfg.ID)
		}
		next.models[cfg.ID] = cfg
	}
	p.stateMu.Lock()
	p.registry = next
	p.ready = true
	if p.active == "" {
		if deployment, err := p.client.AppsV1().Deployments(p.namespace).Get(ctx, p.deployment, metav1.GetOptions{}); err == nil {
			if model := deployment.Spec.Template.Annotations[activeModelAnno]; model != "" {
				if _, ok := next.models[model]; ok {
					p.active = model
					p.activeSince = time.Now()
				}
			}
		}
	}
	p.stateMu.Unlock()
	return nil
}

func parseModelConfig(name string, data map[string]string) (modelConfig, error) {
	cfg := modelConfig{ID: strings.TrimSpace(data["model_id"]), DisplayName: strings.TrimSpace(data["display_name"]), Source: name}
	if cfg.ID == "" || cfg.DisplayName == "" {
		return cfg, errors.New("model_id and display_name are required")
	}
	maxLen, err := strconv.Atoi(data["max_model_len"])
	if err != nil || maxLen < 1 {
		return cfg, errors.New("max_model_len must be a positive integer")
	}
	cfg.MaxModelLen = maxLen
	if cfg.Created, err = time.Parse(time.RFC3339, data["created_at"]); err != nil {
		return cfg, fmt.Errorf("created_at must be RFC3339: %w", err)
	}
	if err := json.Unmarshal([]byte(data["vllm_args.json"]), &cfg.Args); err != nil || len(cfg.Args) == 0 {
		return cfg, errors.New("vllm_args.json must be a non-empty JSON string array")
	}
	for i := range cfg.Args {
		if strings.TrimSpace(cfg.Args[i]) == "" {
			return cfg, errors.New("vllm_args.json cannot contain empty arguments")
		}
	}
	if !contains(cfg.Args, "--model") {
		return cfg, errors.New("vllm_args.json must contain --model")
	}
	return cfg, nil
}

func (p *proxy) models(w http.ResponseWriter, _ *http.Request) {
	p.stateMu.RLock()
	data := make([]map[string]any, 0, len(p.registry.models))
	for _, cfg := range p.registry.models {
		data = append(data, map[string]any{"id": cfg.ID, "object": "model", "created": cfg.Created.Unix(), "owned_by": "vllm-proxy"})
	}
	p.stateMu.RUnlock()
	writeJSON(w, http.StatusOK, map[string]any{"object": "list", "data": data})
}

func (p *proxy) model(w http.ResponseWriter, r *http.Request) {
	p.stateMu.RLock()
	cfg, ok := p.registry.models[r.PathValue("id")]
	p.stateMu.RUnlock()
	if !ok {
		openAIError(w, http.StatusNotFound, "model_not_found", "The requested model is not configured.")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": cfg.ID, "object": "model", "created": cfg.Created.Unix(), "owned_by": "vllm-proxy"})
}

func (p *proxy) inference(w http.ResponseWriter, r *http.Request) {
	var requested string
	if r.Method != http.MethodGet && r.Method != http.MethodDelete {
		body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, p.maxBody))
		if err != nil {
			openAIError(w, http.StatusRequestEntityTooLarge, "invalid_request_error", "Request body is too large.")
			return
		}
		r.Body.Close()
		r.Body = io.NopCloser(bytes.NewReader(body))
		var header struct {
			Model string `json:"model"`
		}
		if json.Unmarshal(body, &header) == nil {
			requested = header.Model
		}
	}
	if requested != "" {
		if err := p.ensureActive(r.Context(), requested); err != nil {
			p.respondTransitionError(w, err)
			return
		}
	} else if !p.isAvailable() {
		p.respondTransitionError(w, errBackendUnavailable)
		return
	}
	p.reverseProxy().ServeHTTP(w, r)
}

var (
	errTransitioning      = errors.New("model transition in progress")
	errBackendUnavailable = errors.New("no active vLLM backend")
)

func (p *proxy) ensureActive(ctx context.Context, requested string) error {
	p.stateMu.Lock()
	cfg, exists := p.registry.models[requested]
	if !exists {
		p.stateMu.Unlock()
		return fmt.Errorf("unknown model %q", requested)
	}
	if p.transitioning {
		p.stateMu.Unlock()
		return errTransitioning
	}
	if p.active == requested {
		p.stateMu.Unlock()
		return nil
	}
	p.transitioning = true
	p.stateMu.Unlock()

	defer func() {
		p.stateMu.Lock()
		p.transitioning = false
		p.stateMu.Unlock()
	}()
	started := time.Now()
	if err := p.transition(ctx, cfg); err != nil {
		return err
	}
	p.switchesTotal.Add(1)
	p.lastSwitch.Store(time.Since(started).Nanoseconds())
	p.stateMu.Lock()
	p.active = cfg.ID
	p.activeSince = time.Now()
	p.stateMu.Unlock()
	return nil
}

func (p *proxy) transition(parent context.Context, cfg modelConfig) error {
	ctx, cancel := context.WithTimeout(parent, p.transitionLimit)
	defer cancel()
	patchedAt := time.Now()
	patch, err := json.Marshal(map[string]any{"spec": map[string]any{"template": map[string]any{
		"metadata": map[string]any{"annotations": map[string]string{activeModelAnno: cfg.ID, switchedAtAnno: time.Now().UTC().Format(time.RFC3339Nano)}},
		"spec":     map[string]any{"containers": []map[string]any{{"name": p.container, "args": cfg.Args}}},
	}}})
	if err != nil {
		return err
	}
	deployment, err := p.client.AppsV1().Deployments(p.namespace).Patch(ctx, p.deployment, types.StrategicMergePatchType, patch, metav1.PatchOptions{})
	if err != nil {
		return fmt.Errorf("patch vLLM Deployment: %w", err)
	}
	for {
		if err := ctx.Err(); err != nil {
			return fmt.Errorf("wait for vLLM rollout: %w", err)
		}
		current, err := p.client.AppsV1().Deployments(p.namespace).Get(ctx, p.deployment, metav1.GetOptions{})
		if err == nil && current.Status.ObservedGeneration >= deployment.Generation && current.Status.UpdatedReplicas == 1 && current.Status.AvailableReplicas == 1 {
			if p.backendHealthy(ctx) {
				p.lastStart.Store(time.Since(patchedAt).Nanoseconds())
				return nil
			}
		}
		select {
		case <-ctx.Done():
		case <-time.After(backendProbeWait):
		}
	}
}

func (p *proxy) backendHealthy(ctx context.Context) bool {
	u := *p.backend
	u.Path = "/health"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return false
	}
	resp, err := p.httpClient.Do(req)
	if err != nil {
		return false
	}
	resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

func (p *proxy) reverseProxy() *httputil.ReverseProxy {
	rp := httputil.NewSingleHostReverseProxy(p.backend)
	rp.FlushInterval = -1
	rp.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, err error) {
		openAIError(w, http.StatusBadGateway, "api_error", "vLLM backend communication failed: "+err.Error())
	}
	return rp
}

func (p *proxy) isAvailable() bool {
	p.stateMu.RLock()
	defer p.stateMu.RUnlock()
	return p.active != "" && !p.transitioning
}

func (p *proxy) respondTransitionError(w http.ResponseWriter, err error) {
	if strings.HasPrefix(err.Error(), "unknown model") {
		openAIError(w, http.StatusNotFound, "model_not_found", err.Error())
		return
	}
	if errors.Is(err, errTransitioning) || errors.Is(err, errBackendUnavailable) {
		w.Header().Set("Retry-After", "15")
		openAIError(w, http.StatusServiceUnavailable, "server_error", err.Error())
		return
	}
	openAIError(w, http.StatusGatewayTimeout, "api_error", err.Error())
}

func (p *proxy) healthz(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) }
func (p *proxy) readyz(w http.ResponseWriter, _ *http.Request) {
	p.stateMu.RLock()
	ready := p.ready
	p.stateMu.RUnlock()
	if !ready {
		http.Error(w, "model registry is not ready", http.StatusServiceUnavailable)
		return
	}
	w.WriteHeader(http.StatusOK)
}

func (p *proxy) metrics(w http.ResponseWriter, r *http.Request) {
	p.stateMu.RLock()
	active, transitioning, activeSince := p.active, p.transitioning, p.activeSince
	p.stateMu.RUnlock()
	w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	if active != "" {
		fmt.Fprintf(w, "vllm_proxy_active_model_info{model_id=%q} 1\n", active)
	}
	fmt.Fprintf(w, "vllm_proxy_transitioning %d\n", boolNumber(transitioning))
	fmt.Fprintf(w, "vllm_proxy_switches_total %d\n", p.switchesTotal.Load())
	fmt.Fprintf(w, "vllm_proxy_config_errors_total %d\n", p.configErrors.Load())
	fmt.Fprintf(w, "vllm_proxy_last_switch_duration_seconds %.6f\n", float64(p.lastSwitch.Load())/float64(time.Second))
	fmt.Fprintf(w, "vllm_proxy_last_startup_duration_seconds %.6f\n", float64(p.lastStart.Load())/float64(time.Second))
	if !activeSince.IsZero() {
		fmt.Fprintf(w, "vllm_proxy_active_model_uptime_seconds %.6f\n", time.Since(activeSince).Seconds())
	}
	u := *p.backend
	u.Path = "/metrics"
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, u.String(), nil)
	if err == nil {
		if resp, err := p.httpClient.Do(req); err == nil {
			defer resp.Body.Close()
			_, _ = io.Copy(w, resp.Body)
		}
	}
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
func openAIError(w http.ResponseWriter, status int, typ, message string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"message": message, "type": typ}})
}
func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
func boolNumber(value bool) int {
	if value {
		return 1
	}
	return 0
}
func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
func durationEnv(key string, fallback time.Duration) time.Duration {
	if value, err := time.ParseDuration(os.Getenv(key)); err == nil && value > 0 {
		return value
	}
	return fallback
}
func int64Env(key string, fallback int64) int64 {
	if value, err := strconv.ParseInt(os.Getenv(key), 10, 64); err == nil && value > 0 {
		return value
	}
	return fallback
}
func mustNamespace() string {
	body, err := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
	if err != nil {
		return "home-infra"
	}
	return strings.TrimSpace(string(body))
}
