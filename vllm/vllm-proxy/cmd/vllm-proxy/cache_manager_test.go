package main

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestCacheUsageUsesMountedTreeWithPVCLimit(t *testing.T) {
	hot := t.TempDir()
	if err := os.WriteFile(filepath.Join(hot, "artifact"), make([]byte, 17), 0o600); err != nil {
		t.Fatal(err)
	}
	m := &cacheManager{limits: map[string]int64{hot: 100}}
	capacity, used, err := m.cacheUsage(hot)
	if err != nil {
		t.Fatal(err)
	}
	if capacity != 100 || used != 17 {
		t.Fatalf("cacheUsage() = (%d, %d), want (100, 17)", capacity, used)
	}
}

func TestDirectoryUsageDoesNotCountSymlinkTarget(t *testing.T) {
	hot := t.TempDir()
	if err := os.WriteFile(filepath.Join(hot, "blob"), make([]byte, 17), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("blob", filepath.Join(hot, "snapshot")); err != nil {
		t.Fatal(err)
	}
	used, err := directoryUsage(hot)
	if err != nil {
		t.Fatal(err)
	}
	if used != 17 {
		t.Fatalf("directoryUsage() = %d, want 17", used)
	}
}

func TestMaterializeFileArtifactUsesRequestedTarget(t *testing.T) {
	artifact, hot := t.TempDir(), t.TempDir()
	payload := filepath.Join(artifact, "payload", "files", "model.gguf")
	if err := os.MkdirAll(filepath.Dir(payload), 0o755); err != nil {
		t.Fatal(err)
	}
	body := []byte("cold model")
	if err := os.WriteFile(payload, body, 0o600); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(body)
	manifest := artifactManifest{Files: []artifactFile{{
		Path: "files/model.gguf", Size: int64(len(body)), SHA256: fmt.Sprintf("%x", digest),
	}}}
	m := &cacheManager{}
	spec := cacheSpec{Kind: "huggingface-files", MaterializationTarget: "gguf/test-model"}
	if err := m.materialize(cacheRequest{Cache: spec}, artifact, hot, manifest); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(hot, "gguf", "test-model", "model.gguf"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(body) {
		t.Fatalf("materialized %q, want %q", got, body)
	}
}

func TestFileCacheTargetValidation(t *testing.T) {
	base := cacheRequest{Model: "model", Backend: "llama-cpp", Cache: cacheSpec{
		Kind: "huggingface-files", RepoID: "example/model", Revision: "0123456789012345678901234567890123456789", Size: 1, Files: []string{"model.gguf"},
	}}
	for _, target := range []string{"", "gguf", "/gguf/model", "../gguf/model", "gguf/../model", "gguf//model"} {
		request := base
		request.Cache.MaterializationTarget = target
		if err := validCacheRequest(request); err == nil {
			t.Errorf("target %q unexpectedly accepted", target)
		}
	}
	base.Cache.MaterializationTarget = "gguf/example-model-012345"
	if err := validCacheRequest(base); err != nil {
		t.Fatalf("valid file target rejected: %v", err)
	}
	hub := base
	hub.Backend, hub.Cache.Kind, hub.Cache.MaterializationTarget = "vllm", "huggingface-hub", "gguf/not-allowed"
	if err := validCacheRequest(hub); err == nil {
		t.Fatal("hub target unexpectedly accepted")
	}
}

func TestEvictionPreservesOtherFileArtifact(t *testing.T) {
	hot := t.TempDir()
	first := cacheSpec{Kind: "huggingface-files", RepoID: "example/first", Revision: "1111111111111111111111111111111111111111", Size: 1, Files: []string{"first.gguf"}, MaterializationTarget: "gguf/first"}
	second := cacheSpec{Kind: "huggingface-files", RepoID: "example/second", Revision: "2222222222222222222222222222222222222222", Size: 1, Files: []string{"second.gguf"}, MaterializationTarget: "gguf/second"}
	for _, spec := range []cacheSpec{first, second} {
		if err := os.MkdirAll(materializedPath(hot, spec), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(materializedPath(hot, spec), spec.Files[0]), []byte("model"), 0o600); err != nil {
			t.Fatal(err)
		}
		marker := filepath.Join(hot, ".llm-cache", cacheKey(spec))
		if err := os.MkdirAll(marker, 0o755); err != nil {
			t.Fatal(err)
		}
		body := []byte(fmt.Sprintf(`{"kind":%q,"repo_id":%q,"revision":%q,"size_bytes":1,"files":[%q],"materialization_target":%q}`, spec.Kind, spec.RepoID, spec.Revision, spec.Files[0], spec.MaterializationTarget))
		if err := os.WriteFile(filepath.Join(marker, "cache.json"), body, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	m := &cacheManager{}
	if err := m.evict(hot, filepath.Join(hot, ".llm-cache", cacheKey(first))); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(materializedPath(hot, first)); !os.IsNotExist(err) {
		t.Fatalf("first artifact still exists: %v", err)
	}
	if _, err := os.Stat(filepath.Join(materializedPath(hot, second), second.Files[0])); err != nil {
		t.Fatalf("second artifact was removed: %v", err)
	}
}
