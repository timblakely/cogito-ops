package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"gopkg.in/yaml.v3"
	appsv1 "k8s.io/api/apps/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/fields"
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
	Name        string
	ModelSource string
	DisplayName string
	MaxModelLen int
	Created     time.Time
	Args        []string
	Source      string
	Fallback    json.RawMessage
	Runtime     json.RawMessage
}

type runtimeMetadata struct {
	SchemaVersion         int               `json:"schema_version"`
	Source                string            `json:"source"`
	ObservedAt            time.Time         `json:"observed_at"`
	ModelName             string            `json:"model_name"`
	ServedModelIDs        []string          `json:"served_model_ids,omitempty"`
	ContextLength         int               `json:"context_length"`
	MaxConcurrentRequests int               `json:"max_concurrent_requests,omitempty"`
	LaunchArguments       map[string]string `json:"launch_arguments"`
	KVCache               map[string]string `json:"kv_cache,omitempty"`
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
	publicBaseURL   string
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
	if len(os.Args) > 1 && os.Args[1] == "generate-config" {
		if err := runGenerateConfig(os.Args[2:], os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, "generate-config:", err)
			os.Exit(1)
		}
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "sync-hermes" {
		if err := runSyncHermes(os.Args[2:], os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, "sync-hermes:", err)
			os.Exit(1)
		}
		return
	}
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
		publicBaseURL:   strings.TrimSuffix(env("PUBLIC_BASE_URL", "http://llm-proxy:8080/v1"), "/"),
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
	go p.reconcileActiveDeployment(logger)
	go p.watchConfigs(logger)
	go p.watchDeployment(logger)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", p.healthz)
	mux.HandleFunc("GET /readyz", p.readyz)
	mux.HandleFunc("GET /metrics", p.metrics)
	mux.HandleFunc("GET /v1/models", p.models)
	mux.HandleFunc("GET /v1/models/{id}", p.model)
	mux.HandleFunc("GET /vllm-proxy/config/{target}", p.hermesConfig)
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

type hermesConfigResponse struct {
	Object   string              `json:"object"`
	Target   string              `json:"target"`
	Config   hermesConfigPayload `json:"config"`
	Metadata map[string]any      `json:"metadata"`
}

type hermesConfigPayload struct {
	Model           hermesModelConfig      `json:"model"`
	CustomProviders []hermesCustomProvider `json:"custom_providers"`
}

type hermesModelConfig struct {
	Default  string `json:"default"`
	Provider string `json:"provider"`
	BaseURL  string `json:"base_url"`
}

type hermesCustomProvider struct {
	Name    string                               `json:"name"`
	BaseURL string                               `json:"base_url"`
	APIMode string                               `json:"api_mode"`
	Models  map[string]hermesCustomProviderModel `json:"models"`
}

type hermesCustomProviderModel struct {
	ContextLength int `json:"context_length"`
}

func (p *proxy) hermesConfig(w http.ResponseWriter, r *http.Request) {
	p.stateMu.RLock()
	cfg, ok := p.registry.models[p.active]
	models := make([]modelConfig, 0, len(p.registry.models))
	for _, model := range p.registry.models {
		models = append(models, model)
	}
	p.stateMu.RUnlock()
	if !ok {
		openAIError(w, http.StatusServiceUnavailable, "server_error", "No active model is available.")
		return
	}
	sort.Slice(models, func(i, j int) bool { return models[i].Name < models[j].Name })
	providerModels := make(map[string]hermesCustomProviderModel, len(models))
	for _, model := range models {
		providerModels[model.Name] = hermesCustomProviderModel{ContextLength: model.MaxModelLen}
	}
	card := modelCard(cfg)
	metadata, _ := card["metadata"].(map[string]any)
	writeJSON(w, http.StatusOK, hermesConfigResponse{
		Object: "vllm_proxy.hermes_config",
		Target: r.PathValue("target"),
		Config: hermesConfigPayload{
			Model: hermesModelConfig{Default: cfg.Name, Provider: "custom:llm-proxy"},
			CustomProviders: []hermesCustomProvider{{
				Name: "llm-proxy", BaseURL: p.publicBaseURL, APIMode: "chat_completions", Models: providerModels,
			}},
		},
		Metadata: metadata,
	})
}

func runSyncHermes(args []string, output io.Writer) error {
	return runSyncHermesWithClient(args, output, http.DefaultClient)
}

func runSyncHermesWithClient(args []string, output io.Writer, client *http.Client) error {
	flags := flag.NewFlagSet("sync-hermes", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	proxyURL := flags.String("proxy-url", env("VLLM_PROXY_URL", ""), "vLLM proxy base URL")
	target := flags.String("target", "hermes-agent", "proxy configuration target")
	configPath := flags.String("config", defaultHermesConfigPath(), "Hermes config.yaml path")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return errors.New("usage: vllm-proxy sync-hermes --proxy-url URL [--config PATH] [--target NAME]")
	}
	if *proxyURL == "" {
		return errors.New("--proxy-url or VLLM_PROXY_URL is required")
	}
	u, err := url.Parse(strings.TrimSuffix(*proxyURL, "/") + "/vllm-proxy/config/" + url.PathEscape(*target))
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return err
	}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("fetch proxy config: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("fetch proxy config: proxy returned %s", resp.Status)
	}
	var remote hermesConfigResponse
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&remote); err != nil {
		return fmt.Errorf("decode proxy config: %w", err)
	}
	if err := validateHermesConfig(remote.Config); err != nil {
		upgraded, upgradeErr := upgradeLegacyHermesConfig(ctx, client, *proxyURL, remote.Config)
		if upgradeErr != nil {
			return fmt.Errorf("invalid proxy Hermes configuration: %w", err)
		}
		remote.Config = upgraded
	}
	if err := writeHermesConfig(*configPath, remote.Config); err != nil {
		return err
	}
	_, err = fmt.Fprintf(output, "Updated %s with active model %s from %s.\n", *configPath, remote.Config.Model.Default, u.String())
	return err
}

type openAIModelsResponse struct {
	Data []struct {
		ID       string `json:"id"`
		Metadata struct {
			ContextLength int `json:"context_length"`
		} `json:"metadata"`
	} `json:"data"`
}

// upgradeLegacyHermesConfig supports a proxy that predates its native Hermes
// catalog endpoint. Its OpenAI-compatible /v1/models response already contains
// the full registry and per-model context limits needed for the catalog.
func upgradeLegacyHermesConfig(ctx context.Context, client *http.Client, proxyURL string, legacy hermesConfigPayload) (hermesConfigPayload, error) {
	if legacy.Model.Provider != "custom" || legacy.Model.Default == "" || legacy.Model.BaseURL == "" {
		return hermesConfigPayload{}, errors.New("not a legacy custom proxy configuration")
	}
	endpoint, err := url.Parse(strings.TrimSuffix(proxyURL, "/") + "/v1/models")
	if err != nil {
		return hermesConfigPayload{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
	if err != nil {
		return hermesConfigPayload{}, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return hermesConfigPayload{}, fmt.Errorf("fetch proxy model catalog: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return hermesConfigPayload{}, fmt.Errorf("fetch proxy model catalog: proxy returned %s", resp.Status)
	}
	var catalog openAIModelsResponse
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&catalog); err != nil {
		return hermesConfigPayload{}, fmt.Errorf("decode proxy model catalog: %w", err)
	}
	models := make(map[string]hermesCustomProviderModel, len(catalog.Data))
	for _, model := range catalog.Data {
		if model.ID == "" || model.Metadata.ContextLength < 1 {
			return hermesConfigPayload{}, errors.New("proxy model catalog contains an invalid model")
		}
		models[model.ID] = hermesCustomProviderModel{ContextLength: model.Metadata.ContextLength}
	}
	return hermesConfigPayload{
		Model: hermesModelConfig{Default: legacy.Model.Default, Provider: "custom:llm-proxy"},
		CustomProviders: []hermesCustomProvider{{
			Name: "llm-proxy", BaseURL: legacy.Model.BaseURL, APIMode: "chat_completions", Models: models,
		}},
	}, nil
}

func defaultHermesConfigPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return "~/.hermes/config.yaml"
	}
	return home + "/.hermes/config.yaml"
}

func validateHermesConfig(remote hermesConfigPayload) error {
	if remote.Model.Default == "" || remote.Model.Provider == "" {
		return errors.New("model.default and model.provider are required")
	}
	if !strings.HasPrefix(remote.Model.Provider, "custom:") {
		return errors.New("model.provider must name a custom provider")
	}
	providerName := strings.TrimPrefix(remote.Model.Provider, "custom:")
	for _, provider := range remote.CustomProviders {
		if provider.Name != providerName {
			continue
		}
		if provider.BaseURL == "" || provider.APIMode != "chat_completions" {
			return errors.New("custom provider requires base_url and chat_completions api_mode")
		}
		model, ok := provider.Models[remote.Model.Default]
		if !ok || model.ContextLength < 1 {
			return errors.New("active model must be present with a positive context_length")
		}
		for id, model := range provider.Models {
			if strings.TrimSpace(id) == "" || model.ContextLength < 1 {
				return errors.New("custom provider models require IDs and positive context_length values")
			}
		}
		return nil
	}
	return fmt.Errorf("custom provider %q is missing", providerName)
}

func writeHermesConfig(path string, remote hermesConfigPayload) error {
	config := map[string]any{}
	if body, err := os.ReadFile(path); err == nil {
		if err := yaml.Unmarshal(body, &config); err != nil {
			return fmt.Errorf("parse Hermes config: %w", err)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if shouldSyncHermesModel(config["model"], remote.Model.Provider) {
		model, ok := config["model"].(map[string]any)
		if !ok {
			model = map[string]any{}
		}
		model["default"] = remote.Model.Default
		model["provider"] = remote.Model.Provider
		delete(model, "base_url")
		delete(model, "api_key")
		delete(model, "api_mode")
		config["model"] = model
	}

	providerName := strings.TrimPrefix(remote.Model.Provider, "custom:")
	providers := make([]any, 0, len(remote.CustomProviders))
	if existing, exists := config["custom_providers"]; exists {
		var ok bool
		providers, ok = existing.([]any)
		if !ok {
			return errors.New("custom_providers must be a YAML list")
		}
	}
	updated := make([]any, 0, len(providers)+1)
	for _, provider := range providers {
		entry, ok := provider.(map[string]any)
		if !ok {
			return errors.New("custom_providers entries must be YAML mappings")
		}
		if entry["name"] == providerName {
			continue
		}
		updated = append(updated, entry)
	}
	for _, provider := range remote.CustomProviders {
		if provider.Name != providerName {
			continue
		}
		models := make(map[string]any, len(provider.Models))
		for id, details := range provider.Models {
			models[id] = map[string]any{"context_length": details.ContextLength}
		}
		updated = append(updated, map[string]any{
			"name": provider.Name, "base_url": provider.BaseURL, "api_mode": provider.APIMode, "models": models,
		})
	}
	config["custom_providers"] = updated
	body, err := yaml.Marshal(config)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	return os.WriteFile(path, body, 0600)
}

func shouldSyncHermesModel(current any, proxyProvider string) bool {
	if current == nil {
		return true
	}
	if sentinel, ok := current.(string); ok {
		return strings.TrimSpace(sentinel) == ""
	}
	model, ok := current.(map[string]any)
	if !ok {
		return false
	}
	provider, _ := model["provider"].(string)
	return provider == "" || provider == proxyProvider
}

func runGenerateConfig(args []string, output io.Writer) error {
	flags := flag.NewFlagSet("generate-config", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	revision := flags.String("revision", "main", "Hugging Face revision containing config.json")
	maxModelLen := flags.Int("max-model-len", 0, "runtime vLLM context cap (defaults to the model-declared limit)")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 1 {
		return errors.New("usage: vllm-proxy generate-config [--revision REVISION] [--max-model-len TOKENS] OWNER/MODEL")
	}
	repo := strings.TrimSpace(flags.Arg(0))
	if len(strings.Split(repo, "/")) != 2 || strings.Contains(repo, " ") {
		return errors.New("model repository must be OWNER/MODEL")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	declared, err := fetchModelContext(ctx, http.DefaultClient, repo, *revision)
	if err != nil {
		return err
	}
	if *maxModelLen < 0 {
		return errors.New("max-model-len must be positive")
	}
	effective := declared
	if *maxModelLen > 0 {
		effective = *maxModelLen
	}
	fallback := map[string]any{"source": "huggingface", "model_max_context": declared}
	if parameters, err := fetchModelParameters(ctx, http.DefaultClient, repo); err == nil && parameters > 0 {
		fallback["total_parameters"] = parameters
	}
	return writeGeneratedConfig(output, repo, declared, effective, fallback)
}

func fetchModelContext(ctx context.Context, client *http.Client, repo, revision string) (int, error) {
	parts := strings.Split(repo, "/")
	url := "https://huggingface.co/" + parts[0] + "/" + parts[1] + "/raw/" + url.PathEscape(revision) + "/config.json"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("User-Agent", "vllm-proxy-config-generator/1")
	resp, err := client.Do(req)
	if err != nil {
		return 0, fmt.Errorf("fetch model config: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("fetch model config: Hugging Face returned %s", resp.Status)
	}
	decoder := json.NewDecoder(io.LimitReader(resp.Body, 1<<20))
	decoder.UseNumber()
	var config map[string]any
	if err := decoder.Decode(&config); err != nil {
		return 0, fmt.Errorf("decode model config: %w", err)
	}
	contextLength, ok := modelContextLength(config)
	if !ok {
		return 0, errors.New("model config does not expose a recognized context-length field; pass a manual profile instead")
	}
	return contextLength, nil
}

func fetchModelParameters(ctx context.Context, client *http.Client, repo string) (int64, error) {
	parts := strings.Split(repo, "/")
	url := "https://huggingface.co/api/models/" + parts[0] + "/" + parts[1]
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("User-Agent", "vllm-proxy-config-generator/1")
	resp, err := client.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("Hugging Face returned %s", resp.Status)
	}
	var payload struct {
		Safetensors struct {
			Total json.Number `json:"total"`
		} `json:"safetensors"`
	}
	decoder := json.NewDecoder(io.LimitReader(resp.Body, 1<<20))
	decoder.UseNumber()
	if err := decoder.Decode(&payload); err != nil {
		return 0, err
	}
	return payload.Safetensors.Total.Int64()
}

func modelContextLength(config map[string]any) (int, bool) {
	keys := []string{"max_position_embeddings", "max_sequence_length", "max_seq_len", "seq_length", "n_positions", "model_max_length"}
	for _, source := range []map[string]any{config, nestedMap(config, "text_config")} {
		for _, key := range keys {
			if value, ok := positiveInt(source[key]); ok && value <= 10_000_000 {
				return value, true
			}
		}
	}
	return 0, false
}

func nestedMap(values map[string]any, key string) map[string]any {
	if nested, ok := values[key].(map[string]any); ok {
		return nested
	}
	return nil
}

func positiveInt(value any) (int, bool) {
	var number int64
	var err error
	switch value := value.(type) {
	case json.Number:
		number, err = value.Int64()
	case string:
		number, err = strconv.ParseInt(value, 10, 64)
	default:
		return 0, false
	}
	return int(number), err == nil && number > 0 && int64(int(number)) == number
}

func writeGeneratedConfig(output io.Writer, repo string, declared, effective int, fallback map[string]any) error {
	args, err := json.Marshal([]string{"--max-model-len", strconv.Itoa(effective), "--host", "0.0.0.0", "--port", "8000"})
	if err != nil {
		return err
	}
	fallbackJSON, err := json.Marshal(fallback)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(output, `---
# Generated from %s/config.json without loading model weights. Review and tune vLLM flags before committing.
apiVersion: v1
kind: ConfigMap
metadata:
  name: llm-model-%s
  labels:
    llm.cogito.dev/model-config: "true"
data:
  model_name: %s
  display_name: %s
  model_max_context: "%d"
  max_model_len: "%d"
  model_card_metadata.json: %s
  created_at: "%s"
  vllm_args.json: %s
	`, repo, modelSlug(repo), yamlQuote(repo), yamlQuote(repo), declared, effective, yamlQuote(string(fallbackJSON)), time.Now().UTC().Format(time.RFC3339), yamlQuote(string(args)))
	return err
}

func modelSlug(value string) string {
	var slug strings.Builder
	lastDash := false
	for _, char := range strings.ToLower(value) {
		if (char >= 'a' && char <= 'z') || (char >= '0' && char <= '9') {
			slug.WriteRune(char)
			lastDash = false
		} else if !lastDash {
			slug.WriteByte('-')
			lastDash = true
		}
	}
	return strings.Trim(slug.String(), "-")
}

func yamlQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "''") + "'"
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
			go p.reconcileActiveDeployment(logger)
		}
	}
}

// watchDeployment keeps the proxy's active-model state aligned with external
// Deployment reconciliations, such as Helm restoring the manifest arguments.
func (p *proxy) watchDeployment(logger *slog.Logger) {
	selector := fields.OneTermEqualSelector("metadata.name", p.deployment).String()
	for {
		watch, err := p.client.AppsV1().Deployments(p.namespace).Watch(context.Background(), metav1.ListOptions{FieldSelector: selector})
		if err != nil {
			p.configErrors.Add(1)
			logger.Warn("watch vLLM Deployment", "error", err)
			time.Sleep(5 * time.Second)
			continue
		}
		for range watch.ResultChan() {
			ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			if err := p.syncActiveDeployment(ctx); err != nil {
				p.configErrors.Add(1)
				logger.Warn("sync active model from vLLM Deployment", "error", err)
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
		if _, exists := next.models[cfg.Name]; exists {
			return fmt.Errorf("duplicate model_name %q", cfg.Name)
		}
		next.models[cfg.Name] = cfg
	}
	p.stateMu.Lock()
	p.registry = next
	p.ready = true
	p.stateMu.Unlock()
	if err := p.syncActiveDeployment(ctx); err != nil {
		return err
	}
	p.stateMu.RLock()
	activeConfig, ok := p.registry.models[p.active]
	p.stateMu.RUnlock()
	if ok && len(activeConfig.Runtime) == 0 && p.backendHealthy(ctx) {
		if err := p.persistRuntimeMetadata(ctx, activeConfig); err != nil {
			p.configErrors.Add(1)
		}
	}
	return nil
}

func (p *proxy) syncActiveDeployment(ctx context.Context) error {
	deployment, err := p.client.AppsV1().Deployments(p.namespace).Get(ctx, p.deployment, metav1.GetOptions{})
	if err != nil {
		return fmt.Errorf("get vLLM Deployment: %w", err)
	}
	model := deployment.Spec.Template.Annotations[activeModelAnno]
	if model == "" {
		return nil
	}
	p.stateMu.Lock()
	defer p.stateMu.Unlock()
	if p.transitioning {
		return nil
	}
	if _, ok := p.registry.models[model]; !ok {
		return fmt.Errorf("vLLM Deployment active model %q is not configured", model)
	}
	if p.active != model {
		p.active = model
		p.activeSince = time.Now()
	}
	return nil
}

func parseModelConfig(name string, data map[string]string) (modelConfig, error) {
	cfg := modelConfig{Name: strings.TrimSpace(data["model_name"]), DisplayName: strings.TrimSpace(data["display_name"]), Source: name}
	if cfg.Name == "" || cfg.DisplayName == "" {
		return cfg, errors.New("model_name and display_name are required")
	}
	cfg.ModelSource = strings.TrimSpace(data["model_source"])
	if cfg.ModelSource == "" {
		cfg.ModelSource = cfg.Name
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
	if contains(cfg.Args, "--model") || contains(cfg.Args, "--served-model-name") {
		return cfg, errors.New("vllm_args.json must not contain --model or --served-model-name")
	}
	if value := data["model_card_metadata.json"]; value != "" && !json.Valid([]byte(value)) {
		return cfg, errors.New("model_card_metadata.json must be valid JSON")
	} else {
		cfg.Fallback = json.RawMessage(value)
	}
	if value := data["runtime_metadata.json"]; value != "" && !json.Valid([]byte(value)) {
		return cfg, errors.New("runtime_metadata.json must be valid JSON")
	} else {
		cfg.Runtime = json.RawMessage(value)
	}
	return cfg, nil
}

func effectiveVLLMArgs(cfg modelConfig) []string {
	args := make([]string, 0, len(cfg.Args)+4)
	args = append(args, "--model", cfg.ModelSource, "--served-model-name", cfg.Name)
	return append(args, cfg.Args...)
}

func deploymentNeedsActivation(deployment *appsv1.Deployment, container string, cfg modelConfig) bool {
	if deployment.Spec.Replicas == nil || *deployment.Spec.Replicas != 1 {
		return true
	}
	want := effectiveVLLMArgs(cfg)
	for _, candidate := range deployment.Spec.Template.Spec.Containers {
		if candidate.Name != container {
			continue
		}
		if len(candidate.Args) != len(want) {
			return true
		}
		for i := range want {
			if candidate.Args[i] != want[i] {
				return true
			}
		}
		return false
	}
	return true
}

// reconcileActiveDeployment materializes the active model ConfigMap into the
// Helm-managed Deployment. Helm owns the pod template; Switchboard owns only
// the selected model arguments and replica count.
func (p *proxy) reconcileActiveDeployment(logger *slog.Logger) {
	ctx, cancel := context.WithTimeout(context.Background(), p.transitionLimit)
	defer cancel()

	p.stateMu.RLock()
	cfg, ok := p.registry.models[p.active]
	p.stateMu.RUnlock()
	if !ok {
		return
	}

	deployment, err := p.client.AppsV1().Deployments(p.namespace).Get(ctx, p.deployment, metav1.GetOptions{})
	if err != nil {
		p.configErrors.Add(1)
		logger.Warn("get vLLM Deployment for active-model reconciliation", "error", err)
		return
	}
	if !deploymentNeedsActivation(deployment, p.container, cfg) {
		return
	}

	p.stateMu.Lock()
	if p.transitioning || p.active != cfg.Name {
		p.stateMu.Unlock()
		return
	}
	p.transitioning = true
	p.stateMu.Unlock()
	defer func() {
		p.stateMu.Lock()
		p.transitioning = false
		p.stateMu.Unlock()
	}()

	if err := p.transition(ctx, cfg); err != nil {
		p.configErrors.Add(1)
		logger.Warn("reconcile active vLLM model", "model", cfg.Name, "error", err)
	}
}

func (p *proxy) models(w http.ResponseWriter, _ *http.Request) {
	p.stateMu.RLock()
	data := make([]map[string]any, 0, len(p.registry.models))
	for _, cfg := range p.registry.models {
		data = append(data, modelCard(cfg))
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
	writeJSON(w, http.StatusOK, modelCard(cfg))
}

func modelCard(cfg modelConfig) map[string]any {
	card := map[string]any{"id": cfg.Name, "object": "model", "created": cfg.Created.Unix(), "owned_by": "vllm-proxy"}
	metadata := map[string]any{"context_length": cfg.MaxModelLen, "source": "manual_config"}
	mergeJSONMetadata(metadata, cfg.Fallback)
	mergeJSONMetadata(metadata, cfg.Runtime)
	card["metadata"] = metadata
	return card
}

func mergeJSONMetadata(destination map[string]any, raw json.RawMessage) {
	if len(raw) == 0 {
		return
	}
	var values map[string]any
	if json.Unmarshal(raw, &values) != nil {
		return
	}
	for key, value := range values {
		destination[key] = value
	}
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
	p.active = cfg.Name
	p.activeSince = time.Now()
	p.stateMu.Unlock()
	return nil
}

func (p *proxy) transition(parent context.Context, cfg modelConfig) error {
	ctx, cancel := context.WithTimeout(parent, p.transitionLimit)
	defer cancel()
	patchedAt := time.Now()
	patch, err := json.Marshal(map[string]any{"spec": map[string]any{"replicas": 1, "template": map[string]any{
		"metadata": map[string]any{"annotations": map[string]string{activeModelAnno: cfg.Name, switchedAtAnno: time.Now().UTC().Format(time.RFC3339Nano)}},
		"spec":     map[string]any{"containers": []map[string]any{{"name": p.container, "args": effectiveVLLMArgs(cfg)}}},
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
				if err := p.persistRuntimeMetadata(ctx, cfg); err != nil {
					p.configErrors.Add(1)
				}
				return nil
			}
		}
		select {
		case <-ctx.Done():
		case <-time.After(backendProbeWait):
		}
	}
}

func (p *proxy) persistRuntimeMetadata(ctx context.Context, cfg modelConfig) error {
	metadata, err := p.collectRuntimeMetadata(ctx, cfg)
	if err != nil {
		return err
	}
	body, err := json.Marshal(metadata)
	if err != nil {
		return err
	}
	configMap, err := p.client.CoreV1().ConfigMaps(p.namespace).Get(ctx, cfg.Source, metav1.GetOptions{})
	if err != nil {
		return fmt.Errorf("read model ConfigMap: %w", err)
	}
	data := map[string]string{"runtime_metadata.json": string(body)}
	if configMap.Data["model_card_metadata.json"] == "" {
		if fallback, err := p.modelCardFallback(ctx, cfg); err == nil {
			data["model_card_metadata.json"] = fallback
		}
	}
	patch, err := json.Marshal(map[string]any{"data": data})
	if err != nil {
		return err
	}
	_, err = p.client.CoreV1().ConfigMaps(p.namespace).Patch(ctx, cfg.Source, types.MergePatchType, patch, metav1.PatchOptions{FieldManager: "vllm-proxy"})
	if err != nil {
		return fmt.Errorf("persist runtime metadata: %w", err)
	}
	return nil
}

func (p *proxy) modelCardFallback(ctx context.Context, cfg modelConfig) (string, error) {
	repo := cfg.ModelSource
	if len(strings.Split(repo, "/")) != 2 {
		return "", errors.New("model repository is not OWNER/MODEL")
	}
	metadata := map[string]any{"source": "huggingface", "model_max_context": cfg.MaxModelLen}
	if declared, err := fetchModelContext(ctx, p.httpClient, repo, "main"); err == nil {
		metadata["model_max_context"] = declared
	}
	if parameters, err := fetchModelParameters(ctx, p.httpClient, repo); err == nil && parameters > 0 {
		metadata["total_parameters"] = parameters
	}
	body, err := json.Marshal(metadata)
	return string(body), err
}

func (p *proxy) collectRuntimeMetadata(ctx context.Context, cfg modelConfig) (runtimeMetadata, error) {
	metadata := runtimeMetadata{
		SchemaVersion:   1,
		Source:          "vllm_runtime",
		ObservedAt:      time.Now().UTC(),
		ModelName:       cfg.Name,
		ContextLength:   cfg.MaxModelLen,
		LaunchArguments: launchArguments(effectiveVLLMArgs(cfg)),
	}
	metadata.MaxConcurrentRequests, _ = strconv.Atoi(metadata.LaunchArguments["--max-num-seqs"])
	metrics, err := p.backendText(ctx, "/metrics")
	if err == nil {
		metadata.KVCache = cacheConfigInfo(metrics)
	}
	models, err := p.backendModels(ctx)
	if err == nil {
		metadata.ServedModelIDs = models
	}
	return metadata, nil
}

func (p *proxy) backendText(ctx context.Context, endpoint string) (string, error) {
	u := *p.backend
	u.Path = endpoint
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return "", err
	}
	resp, err := p.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("backend %s returned %s", endpoint, resp.Status)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	return string(body), err
}

func (p *proxy) backendModels(ctx context.Context) ([]string, error) {
	body, err := p.backendText(ctx, "/v1/models")
	if err != nil {
		return nil, err
	}
	var response struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
	}
	if err := json.Unmarshal([]byte(body), &response); err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(response.Data))
	for _, model := range response.Data {
		if model.ID != "" {
			ids = append(ids, model.ID)
		}
	}
	return ids, nil
}

func launchArguments(args []string) map[string]string {
	values := map[string]string{}
	for index := 0; index < len(args); index++ {
		if !strings.HasPrefix(args[index], "--") {
			continue
		}
		if index+1 < len(args) && !strings.HasPrefix(args[index+1], "--") {
			values[args[index]] = args[index+1]
			index++
		} else {
			values[args[index]] = "true"
		}
	}
	return values
}

func cacheConfigInfo(metrics string) map[string]string {
	scanner := bufio.NewScanner(strings.NewReader(metrics))
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "vllm:cache_config_info{") {
			continue
		}
		start, end := strings.IndexByte(line, '{'), strings.LastIndex(line, "}")
		if start < 0 || end <= start {
			return nil
		}
		return prometheusLabels(line[start+1 : end])
	}
	return nil
}

func prometheusLabels(encoded string) map[string]string {
	labels := map[string]string{}
	for len(encoded) > 0 {
		equals := strings.IndexByte(encoded, '=')
		if equals < 1 || equals+1 >= len(encoded) || encoded[equals+1] != '"' {
			return labels
		}
		key := encoded[:equals]
		encoded = encoded[equals+1:]
		end := 1
		for end < len(encoded) {
			if encoded[end] == '"' && encoded[end-1] != '\\' {
				break
			}
			end++
		}
		if end == len(encoded) {
			return labels
		}
		value, err := strconv.Unquote(encoded[:end+1])
		if err != nil {
			return labels
		}
		labels[key] = value
		encoded = strings.TrimPrefix(encoded[end+1:], ",")
	}
	return labels
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
		fmt.Fprintf(w, "vllm_proxy_active_model_info{model_name=%q} 1\n", active)
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
