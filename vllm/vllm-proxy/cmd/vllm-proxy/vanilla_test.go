package main

import (
	"context"
	"net/url"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

func TestSyncActiveDeploymentSelectsVanillaLlamaBackend(t *testing.T) {
	zero, one := int32(0), int32(1)
	vanillaURL, _ := url.Parse("http://llm-llama-cpp:8000")
	client := fake.NewSimpleClientset(
		&appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: "llm-vllm", Namespace: "home-infra"}, Spec: appsv1.DeploymentSpec{Replicas: &zero}},
		&appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: "laguna", Namespace: "home-infra"}, Spec: appsv1.DeploymentSpec{Replicas: &zero}},
		&appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: "llm-llama-cpp", Namespace: "home-infra"}, Spec: appsv1.DeploymentSpec{Replicas: &one, Template: corev1.PodTemplateSpec{ObjectMeta: metav1.ObjectMeta{Annotations: map[string]string{activeModelAnno: "vanilla-model"}}}}},
	)
	p := &proxy{
		client: client, namespace: "home-infra", active: "gemma",
		backends: map[string]backendConfig{
			"vllm":              {Name: "vllm", Deployment: "llm-vllm"},
			"llama-cpp":          {Name: "llama-cpp", Deployment: "laguna"},
			"llama-cpp-vanilla": {Name: "llama-cpp-vanilla", Deployment: "llm-llama-cpp", URL: vanillaURL},
		},
		registry: registry{models: map[string]modelConfig{"vanilla-model": {Name: "vanilla-model", Backend: "llama-cpp-vanilla"}}},
	}
	if err := p.syncActiveDeployment(context.Background()); err != nil {
		t.Fatal(err)
	}
	if p.active != "vanilla-model" || p.backendName != "llama-cpp-vanilla" || p.backend.String() != vanillaURL.String() {
		t.Fatalf("unexpected active backend: model=%q backend=%q url=%v", p.active, p.backendName, p.backend)
	}
}

func TestParseVanillaLlamaModelConfig(t *testing.T) {
	cfg, err := parseModelConfig("vanilla-model", map[string]string{
		"backend": "llama-cpp-vanilla", "model_name": "example/model", "model_source": "/models/model.gguf", "display_name": "Vanilla Llama", "max_model_len": "32768", "created_at": "2026-07-27T00:00:00Z",
		"llama_args.json": `["--ctx-size","32768"]`,
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Backend != "llama-cpp-vanilla" {
		t.Fatalf("backend = %q, want llama-cpp-vanilla", cfg.Backend)
	}
}
