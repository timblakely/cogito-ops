package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestParseModelConfig(t *testing.T) {
	cfg, err := parseModelConfig("gemma", map[string]string{
		"model_id": "gemma-4", "display_name": "Gemma 4", "max_model_len": "8192", "created_at": "2026-07-11T00:00:00Z",
		"vllm_args.json": `["serve","--model","example/gemma","--override-generation-config","{\"top_p\":0.9}"]`,
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.MaxModelLen != 8192 || cfg.Args[4] != `{"top_p":0.9}` {
		t.Fatalf("unexpected config: %#v", cfg)
	}
}

func TestParseModelConfigRejectsInvalidArgs(t *testing.T) {
	_, err := parseModelConfig("invalid", map[string]string{
		"model_id": "invalid", "display_name": "Invalid", "max_model_len": "1", "created_at": "2026-07-11T00:00:00Z", "vllm_args.json": `["serve"]`,
	})
	if err == nil {
		t.Fatal("expected validation error")
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
	if err := writeGeneratedConfig(&output, "NousResearch/Hermes-3-Llama-3.1-8B", "hermes-3", 131072, 65536, map[string]any{"model_max_context": 131072}); err != nil {
		t.Fatal(err)
	}
	config := output.String()
	for _, want := range []string{"model_max_context: \"131072\"", "max_model_len: \"65536\"", "model_card_metadata.json", "--model"} {
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
	cfg := modelConfig{ID: "model", Created: time.Unix(1, 0), Fallback: json.RawMessage(`{"source":"huggingface"}`), Runtime: json.RawMessage(`{"source":"vllm_runtime"}`)}
	metadata, ok := modelCard(cfg)["metadata"].(map[string]any)
	if !ok || metadata["source"] != "vllm_runtime" {
		t.Fatalf("runtime metadata was not selected: %#v", modelCard(cfg))
	}
}

func TestHermesConfigEndpointUsesActiveModel(t *testing.T) {
	p := &proxy{registry: registry{models: map[string]modelConfig{"gemma": {ID: "gemma", Created: time.Unix(1, 0), Runtime: json.RawMessage(`{"context_length":32768}`)}}}, active: "gemma", publicBaseURL: "https://llm.example/v1", hermesAPIKey: "local-key"}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest("GET", "/vllm-proxy/config/hermes-agent", nil)
	p.hermesConfig(recorder, request)
	if recorder.Code != 200 || !strings.Contains(recorder.Body.String(), `"default":"gemma"`) || !strings.Contains(recorder.Body.String(), `"context_length":32768`) {
		t.Fatalf("unexpected config endpoint response: %d %s", recorder.Code, recorder.Body.String())
	}
}

func TestWriteHermesConfigPreservesOtherSettings(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "config.yaml")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("agent:\n  max_turns: 20\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := writeHermesConfig(path, map[string]any{"default": "gemma", "provider": "custom", "base_url": "https://llm.example/v1", "api_key": "local-key"}); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"max_turns: 20", "default: gemma", "provider: custom", "base_url: https://llm.example/v1"} {
		if !strings.Contains(string(body), want) {
			t.Fatalf("updated config missing %q:\n%s", want, body)
		}
	}
}

func TestRunSyncHermes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Status: "200 OK", Body: io.NopCloser(strings.NewReader(`{"object":"vllm_proxy.hermes_config","target":"hermes-agent","config":{"model":{"default":"gemma","provider":"custom","base_url":"https://llm.example/v1","api_key":"local-key"}},"metadata":{}}`)), Header: make(http.Header)}, nil
	})}
	if err := runSyncHermesWithClient([]string{"--proxy-url", "https://llm.example", "--config", path}, io.Discard, client); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(body), "default: gemma") {
		t.Fatalf("unexpected synced config:\n%s", body)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return fn(request) }
