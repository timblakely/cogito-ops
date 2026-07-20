package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

func TestSyncActiveDeploymentReconcilesExternalModelChange(t *testing.T) {
	client := fake.NewSimpleClientset(&appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{Name: "llm-vllm", Namespace: "home-infra"},
		Spec: appsv1.DeploymentSpec{Template: corev1.PodTemplateSpec{ObjectMeta: metav1.ObjectMeta{
			Annotations: map[string]string{activeModelAnno: "gemma"},
		}}},
	})
	p := &proxy{
		client: client, namespace: "home-infra", deployment: "llm-vllm", active: "qwen",
		registry: registry{models: map[string]modelConfig{"gemma": {Name: "gemma"}, "qwen": {Name: "qwen"}}},
	}
	if err := p.syncActiveDeployment(context.Background()); err != nil {
		t.Fatal(err)
	}
	if p.active != "gemma" {
		t.Fatalf("active model = %q, want gemma", p.active)
	}
}

func TestReconcileActiveDeploymentCancelsStaleTransition(t *testing.T) {
	replicas := int32(1)
	client := fake.NewSimpleClientset(&appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{Name: "llm-vllm", Namespace: "home-infra"},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Template: corev1.PodTemplateSpec{Spec: corev1.PodSpec{Containers: []corev1.Container{{Name: "vllm"}}}},
		},
	})
	canceled := make(chan struct{})
	p := &proxy{
		client:           client,
		namespace:        "home-infra",
		deployment:       "llm-vllm",
		container:        "vllm",
		active:           "gemma",
		transitioning:    true,
		transitionCancel: func() { close(canceled) },
		registry: registry{models: map[string]modelConfig{
			"gemma": {Name: "gemma", ModelSource: "google/gemma"},
		}},
	}

	p.reconcileActiveDeployment(slog.New(slog.NewTextHandler(io.Discard, nil)))
	select {
	case <-canceled:
	case <-time.After(time.Second):
		t.Fatal("stale transition was not canceled")
	}
	if !p.reconcilePending {
		t.Fatal("updated active model was not queued for reconciliation")
	}
}

func TestSyncActiveDeploymentPreservesInFlightTransition(t *testing.T) {
	client := fake.NewSimpleClientset(&appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{Name: "llm-vllm", Namespace: "home-infra"},
		Spec: appsv1.DeploymentSpec{Template: corev1.PodTemplateSpec{ObjectMeta: metav1.ObjectMeta{
			Annotations: map[string]string{activeModelAnno: "gemma"},
		}}},
	})
	p := &proxy{
		client: client, namespace: "home-infra", deployment: "llm-vllm", active: "qwen", transitioning: true,
		registry: registry{models: map[string]modelConfig{"gemma": {Name: "gemma"}, "qwen": {Name: "qwen"}}},
	}
	if err := p.syncActiveDeployment(context.Background()); err != nil {
		t.Fatal(err)
	}
	if p.active != "qwen" {
		t.Fatalf("active model = %q, want qwen during transition", p.active)
	}
}

func TestParseModelConfig(t *testing.T) {
	cfg, err := parseModelConfig("gemma", map[string]string{
		"model_name": "benchmark/gemma", "model_source": "example/gemma", "display_name": "Gemma 4", "max_model_len": "8192", "created_at": "2026-07-11T00:00:00Z",
		"vllm_args.json": `["--override-generation-config","{\"top_p\":0.9}"]`,
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.MaxModelLen != 8192 || cfg.Name != "benchmark/gemma" || cfg.ModelSource != "example/gemma" || cfg.Args[1] != `{"top_p":0.9}` {
		t.Fatalf("unexpected config: %#v", cfg)
	}
	args := effectiveVLLMArgs(cfg)
	if strings.Join(args, " ") != `--model example/gemma --served-model-name benchmark/gemma --override-generation-config {"top_p":0.9}` {
		t.Fatalf("unexpected effective arguments: %#v", args)
	}
}

func TestParseModelConfigRejectsInvalidArgs(t *testing.T) {
	_, err := parseModelConfig("invalid", map[string]string{
		"model_name": "example/invalid", "display_name": "Invalid", "max_model_len": "1", "created_at": "2026-07-11T00:00:00Z", "vllm_args.json": `["--model","example/invalid"]`,
	})
	if err == nil {
		t.Fatal("expected validation error")
	}
}

func TestParseModelConfigDefaultsModelSourceToModelName(t *testing.T) {
	cfg, err := parseModelConfig("gemma", map[string]string{
		"model_name": "example/gemma", "display_name": "Gemma 4", "max_model_len": "8192", "created_at": "2026-07-11T00:00:00Z",
		"vllm_args.json": `["--host","0.0.0.0"]`,
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.ModelSource != cfg.Name {
		t.Fatalf("model source = %q, want %q", cfg.ModelSource, cfg.Name)
	}
}

func TestDeploymentNeedsActivation(t *testing.T) {
	replicas := int32(1)
	cfg := modelConfig{Name: "gemma", ModelSource: "google/gemma", Args: []string{"--host", "0.0.0.0"}}
	deployment := &appsv1.Deployment{Spec: appsv1.DeploymentSpec{
		Replicas: &replicas,
		Template: corev1.PodTemplateSpec{Spec: corev1.PodSpec{Containers: []corev1.Container{{
			Name: "vllm", Args: effectiveVLLMArgs(cfg),
		}}}},
	}}
	if deploymentNeedsActivation(deployment, "vllm", cfg) {
		t.Fatal("matching one-replica Deployment should not require activation")
	}

	zero := int32(0)
	deployment.Spec.Replicas = &zero
	if !deploymentNeedsActivation(deployment, "vllm", cfg) {
		t.Fatal("zero-replica Deployment should require activation")
	}

	deployment.Spec.Replicas = &replicas
	deployment.Spec.Template.Spec.Containers[0].Args = []string{"--model", "wrong"}
	if !deploymentNeedsActivation(deployment, "vllm", cfg) {
		t.Fatal("Deployment with stale arguments should require activation")
	}
}

func TestModelContextLength(t *testing.T) {
	length, ok := modelContextLength(map[string]any{"text_config": map[string]any{"max_position_embeddings": json.Number("131072")}})
	if !ok || length != 131072 {
		t.Fatalf("got (%d, %t), want (131072, true)", length, ok)
	}
}

func TestWriteGeneratedConfig(t *testing.T) {
	var output bytes.Buffer
	if err := writeGeneratedConfig(&output, "NousResearch/Hermes-3-Llama-3.1-8B", 131072, 65536, map[string]any{"model_max_context": 131072}); err != nil {
		t.Fatal(err)
	}
	config := output.String()
	for _, want := range []string{"model_name: 'NousResearch/Hermes-3-Llama-3.1-8B'", "model_max_context: \"131072\"", "max_model_len: \"65536\"", "model_card_metadata.json"} {
		if !strings.Contains(config, want) {
			t.Fatalf("generated config missing %q:\n%s", want, config)
		}
	}
}

func TestCacheConfigInfo(t *testing.T) {
	metrics := "# HELP vllm:cache_config_info Information\n" +
		"vllm:cache_config_info{block_size=\"16\",cache_dtype=\"fp8_e5m2\",gpu_memory_utilization=\"0.92\",num_gpu_blocks=\"4096\"} 1\n"
	cache := cacheConfigInfo(metrics)
	if cache["block_size"] != "16" || cache["num_gpu_blocks"] != "4096" {
		t.Fatalf("unexpected cache metadata: %#v", cache)
	}
}

func TestModelCardPrefersRuntimeMetadata(t *testing.T) {
	cfg := modelConfig{Name: "model", Created: time.Unix(1, 0), Fallback: json.RawMessage(`{"source":"huggingface"}`), Runtime: json.RawMessage(`{"source":"vllm_runtime"}`)}
	metadata, ok := modelCard(cfg)["metadata"].(map[string]any)
	if !ok || metadata["source"] != "vllm_runtime" {
		t.Fatalf("runtime metadata was not selected: %#v", modelCard(cfg))
	}
}

func TestHermesConfigEndpointUsesActiveModel(t *testing.T) {
	p := &proxy{registry: registry{models: map[string]modelConfig{
		"gemma": {Name: "gemma", MaxModelLen: 32768, Created: time.Unix(1, 0)},
		"qwen":  {Name: "qwen", MaxModelLen: 65536, Created: time.Unix(2, 0)},
	}}, active: "gemma", publicBaseURL: "https://llm.example/v1"}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest("GET", "/vllm-proxy/config/hermes-agent", nil)
	p.hermesConfig(recorder, request)
	for _, want := range []string{`"default":"gemma"`, `"provider":"custom:llm-proxy"`, `"name":"llm-proxy"`, `"gemma":{"context_length":32768}`, `"qwen":{"context_length":65536}`} {
		if recorder.Code != 200 || !strings.Contains(recorder.Body.String(), want) {
			t.Fatalf("unexpected config endpoint response: %d %s", recorder.Code, recorder.Body.String())
		}
	}
	if strings.Contains(recorder.Body.String(), `"api_key"`) {
		t.Fatalf("unexpected config endpoint response: %d %s", recorder.Code, recorder.Body.String())
	}
}

func TestWriteHermesConfigPreservesOtherSettings(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "config.yaml")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("agent:\n  max_turns: 20\ncustom_providers:\n  - name: other\n    base_url: https://other.example/v1\n  - name: llm-proxy\n    base_url: https://old.example/v1\n    models:\n      stale:\n        context_length: 1\nmodel:\n  aliases:\n    fav: custom:llm-proxy:gemma\n  provider: custom:llm-proxy\n  base_url: https://old.example/v1\n"), 0600); err != nil {
		t.Fatal(err)
	}
	remote := hermesConfigPayload{
		Model: hermesModelConfig{Default: "gemma", Provider: "custom:llm-proxy"},
		CustomProviders: []hermesCustomProvider{{Name: "llm-proxy", BaseURL: "https://llm.example/v1", APIMode: "chat_completions", Models: map[string]hermesCustomProviderModel{
			"gemma": {ContextLength: 32768}, "qwen": {ContextLength: 65536},
		}}},
	}
	if err := writeHermesConfig(path, remote); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"max_turns: 20", "default: gemma", "provider: custom:llm-proxy", "base_url: https://llm.example/v1", "name: other", "name: llm-proxy", "context_length: 32768", "context_length: 65536", "fav: custom:llm-proxy:gemma"} {
		if !strings.Contains(string(body), want) {
			t.Fatalf("updated config missing %q:\n%s", want, body)
		}
	}
	if strings.Contains(string(body), "stale") || strings.Contains(string(body), "https://old.example") {
		t.Fatalf("stale proxy configuration remained:\n%s", body)
	}
}

func TestWriteHermesConfigPreservesOpenAIModelSelection(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	original := "model:\n  provider: openai-api\n  default: gpt-5\n  base_url: https://api.openai.example/v1\ncustom_providers:\n  - name: llm-proxy\n    base_url: https://old.example/v1\n    models:\n      stale:\n        context_length: 1\n"
	if err := os.WriteFile(path, []byte(original), 0600); err != nil {
		t.Fatal(err)
	}
	remote := hermesConfigPayload{
		Model: hermesModelConfig{Default: "gemma", Provider: "custom:llm-proxy"},
		CustomProviders: []hermesCustomProvider{{Name: "llm-proxy", BaseURL: "https://llm.example/v1", APIMode: "chat_completions", Models: map[string]hermesCustomProviderModel{
			"gemma": {ContextLength: 32768},
		}}},
	}
	if err := writeHermesConfig(path, remote); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"provider: openai-api", "default: gpt-5", "base_url: https://api.openai.example/v1", "name: llm-proxy", "base_url: https://llm.example/v1", "context_length: 32768"} {
		if !strings.Contains(string(body), want) {
			t.Fatalf("synced config missing %q:\n%s", want, body)
		}
	}
	if strings.Contains(string(body), "stale") || strings.Contains(string(body), "default: gemma") {
		t.Fatalf("unexpected proxy model overwrite:\n%s", body)
	}
}

func TestBootstrapHermesConfigSeedsDynamicProvider(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "config.yaml")
	remote := hermesConfigPayload{
		Model: hermesModelConfig{Default: "gemma", Provider: "custom:llm-proxy"},
		CustomProviders: []hermesCustomProvider{{Name: "llm-proxy", BaseURL: "https://llm.example/v1", APIMode: "chat_completions", Models: map[string]hermesCustomProviderModel{
			"gemma": {ContextLength: 32768}, "qwen": {ContextLength: 65536},
		}}},
	}
	changed, err := bootstrapHermesConfig(path, remote)
	if err != nil || !changed {
		t.Fatalf("bootstrapHermesConfig changed=%v err=%v", changed, err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"provider: custom:llm-proxy", "default: gemma", "name: llm-proxy", "base_url: https://llm.example/v1", "api_mode: chat_completions", "discover_models: true"} {
		if !strings.Contains(string(body), want) {
			t.Fatalf("bootstrap config missing %q:\n%s", want, body)
		}
	}
	if strings.Contains(string(body), "context_length") || strings.Contains(string(body), "qwen") {
		t.Fatalf("bootstrap should not persist a model catalog:\n%s", body)
	}
}

func TestBootstrapHermesConfigPreservesExistingChoices(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	original := "model:\n  provider: openai-api\n  default: gpt-5\ncustom_providers:\n  - name: llm-proxy\n    base_url: https://custom.example/v1\n    extra_body:\n      chat_template_kwargs:\n        enable_thinking: true\n"
	if err := os.WriteFile(path, []byte(original), 0600); err != nil {
		t.Fatal(err)
	}
	remote := hermesConfigPayload{
		Model:           hermesModelConfig{Default: "gemma", Provider: "custom:llm-proxy"},
		CustomProviders: []hermesCustomProvider{{Name: "llm-proxy", BaseURL: "https://llm.example/v1", APIMode: "chat_completions", Models: map[string]hermesCustomProviderModel{"gemma": {ContextLength: 32768}}}},
	}
	changed, err := bootstrapHermesConfig(path, remote)
	if err != nil || changed {
		t.Fatalf("bootstrapHermesConfig changed=%v err=%v", changed, err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(body) != original {
		t.Fatalf("existing config changed:\n%s", body)
	}
}

func TestBootstrapHermesConfigCompletesProxyModelWithoutReplacingProvider(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte("model:\n  provider: custom:llm-proxy\nagent:\n  max_turns: 20\n"), 0600); err != nil {
		t.Fatal(err)
	}
	remote := hermesConfigPayload{
		Model:           hermesModelConfig{Default: "gemma", Provider: "custom:llm-proxy"},
		CustomProviders: []hermesCustomProvider{{Name: "llm-proxy", BaseURL: "https://llm.example/v1", APIMode: "chat_completions", Models: map[string]hermesCustomProviderModel{"gemma": {ContextLength: 32768}}}},
	}
	changed, err := bootstrapHermesConfig(path, remote)
	if err != nil || !changed {
		t.Fatalf("bootstrapHermesConfig changed=%v err=%v", changed, err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"max_turns: 20", "provider: custom:llm-proxy", "default: gemma", "discover_models: true"} {
		if !strings.Contains(string(body), want) {
			t.Fatalf("bootstrap config missing %q:\n%s", want, body)
		}
	}
}

func TestRunSyncHermes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Status: "200 OK", Body: io.NopCloser(strings.NewReader(`{"object":"vllm_proxy.hermes_config","target":"hermes-agent","config":{"model":{"default":"gemma","provider":"custom:llm-proxy"},"custom_providers":[{"name":"llm-proxy","base_url":"https://llm.example/v1","api_mode":"chat_completions","models":{"gemma":{"context_length":32768}}}]},"metadata":{}}`)), Header: make(http.Header)}, nil
	})}
	if err := runSyncHermesWithClient([]string{"--proxy-url", "https://llm.example", "--config", path}, io.Discard, client); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(body), "default: gemma") || !strings.Contains(string(body), "provider: custom:llm-proxy") || !strings.Contains(string(body), "context_length: 32768") {
		t.Fatalf("unexpected synced config:\n%s", body)
	}
}

func TestRunBootstrapHermes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Status: "200 OK", Body: io.NopCloser(strings.NewReader(`{"object":"vllm_proxy.hermes_config","target":"hermes-agent","config":{"model":{"default":"gemma","provider":"custom:llm-proxy"},"custom_providers":[{"name":"llm-proxy","base_url":"https://llm.example/v1","api_mode":"chat_completions","models":{"gemma":{"context_length":32768}}}]},"metadata":{}}`)), Header: make(http.Header)}, nil
	})}
	if err := runBootstrapHermesWithClient([]string{"--proxy-url", "https://llm.example", "--config", path}, io.Discard, client); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(body), "default: gemma") || !strings.Contains(string(body), "discover_models: true") || strings.Contains(string(body), "context_length") {
		t.Fatalf("unexpected bootstrap config:\n%s", body)
	}
}

func TestValidateHermesConfigRejectsInvalidActiveModel(t *testing.T) {
	err := validateHermesConfig(hermesConfigPayload{
		Model: hermesModelConfig{Default: "missing", Provider: "custom:llm-proxy"},
		CustomProviders: []hermesCustomProvider{{Name: "llm-proxy", BaseURL: "https://llm.example/v1", APIMode: "chat_completions", Models: map[string]hermesCustomProviderModel{
			"gemma": {ContextLength: 32768},
		}}},
	})
	if err == nil {
		t.Fatal("expected validation error")
	}
}

func TestUpgradeLegacyHermesConfigReadsModelCatalog(t *testing.T) {
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.String() != "https://llm.example/v1/models" {
			t.Fatalf("unexpected catalog URL: %s", request.URL)
		}
		body := `{"object":"list","data":[{"id":"gemma","metadata":{"context_length":32768}},{"id":"qwen","metadata":{"context_length":65536}}]}`
		return &http.Response{StatusCode: 200, Status: "200 OK", Body: io.NopCloser(strings.NewReader(body)), Header: make(http.Header)}, nil
	})}
	upgraded, err := upgradeLegacyHermesConfig(context.Background(), client, "https://llm.example", hermesConfigPayload{
		Model: hermesModelConfig{Default: "gemma", Provider: "custom", BaseURL: "https://llm.example/v1"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := validateHermesConfig(upgraded); err != nil {
		t.Fatalf("upgraded config is invalid: %v", err)
	}
	if upgraded.Model.Provider != "custom:llm-proxy" || upgraded.CustomProviders[0].Models["qwen"].ContextLength != 65536 {
		t.Fatalf("unexpected upgraded config: %#v", upgraded)
	}
}

func TestInferenceForwardsCanonicalModelName(t *testing.T) {
	const modelName = "Lorbus/Qwen3.6-27B-int4-AutoRound"
	var receivedModel string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var payload struct {
			Model string `json:"model"`
		}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		receivedModel = payload.Model
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer backend.Close()
	backendURL, err := url.Parse(backend.URL)
	if err != nil {
		t.Fatal(err)
	}
	p := &proxy{
		backend: backendURL,
		registry: registry{models: map[string]modelConfig{
			modelName: {Name: modelName},
		}},
		active:  modelName,
		maxBody: 1 << 20,
	}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(`{"model":"`+modelName+`","messages":[]}`))
	p.inference(recorder, request)
	if recorder.Code != http.StatusOK || receivedModel != modelName {
		t.Fatalf("got status=%d backend model=%q, want %q", recorder.Code, receivedModel, modelName)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return fn(request) }
