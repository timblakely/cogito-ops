package main

import "testing"

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
