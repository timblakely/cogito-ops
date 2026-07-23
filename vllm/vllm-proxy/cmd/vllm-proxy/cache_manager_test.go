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

func TestMaterializeFileArtifactStripsPayloadPrefix(t *testing.T) {
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
	if err := m.materialize(cacheRequest{Cache: cacheSpec{Kind: "huggingface-files"}}, artifact, hot, manifest); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(hot, "laguna", "model.gguf"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(body) {
		t.Fatalf("materialized %q, want %q", got, body)
	}
}
