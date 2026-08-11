REGISTRY ?= ghcr.io/timblakely
TAG ?= dev

PROXY_IMAGE := $(REGISTRY)/vllm-proxy:$(TAG)
CACHE_MANAGER_IMAGE := $(REGISTRY)/llm-cache-manager:$(TAG)
OPENAI_IMAGE := $(REGISTRY)/vllm-openai:$(TAG)
LAGUNA_IMAGE := $(REGISTRY)/llama-laguna:$(TAG)
MUSE_IMAGE := $(REGISTRY)/llama-muse:$(TAG)
# Poolside PR #3, pinned to its single commit until it is merged into laguna.
LAGUNA_CONTEXT := https://github.com/rpw/llama.cpp.git?branch=patch-1&checksum=ffbd3e3f62cb32d0cbe9c496a9d57e19aef5677d
# Muse Glimmer support was merged upstream in this commit. Keep the runtime
# source pinned: the release images used by the other llama.cpp backends
# predate the architecture and its multimodal projector support.
MUSE_CONTEXT := https://github.com/ggml-org/llama.cpp.git?ref=62bf73d25c53b8161f8a22894d4f90c4aebbd7d0&checksum=62bf73d25c53b8161f8a22894d4f90c4aebbd7d0

.PHONY: build-proxy push-proxy build-cache-manager push-cache-manager build-openai push-openai build-laguna push-laguna build-muse push-muse

build-proxy:
	docker build --target proxy --tag $(PROXY_IMAGE) vllm-proxy

push-proxy:
	docker buildx build --target proxy --push --tag $(PROXY_IMAGE) vllm-proxy

build-cache-manager:
	docker build --target cache-manager --tag $(CACHE_MANAGER_IMAGE) vllm-proxy

push-cache-manager:
	docker buildx build --target cache-manager --push --tag $(CACHE_MANAGER_IMAGE) vllm-proxy

build-openai:
	docker build --tag $(OPENAI_IMAGE) vllm-openai

push-openai:
	docker buildx build --push --tag $(OPENAI_IMAGE) vllm-openai

build-laguna:
	docker build --file .devops/cuda.Dockerfile --target server --build-arg CUDA_DOCKER_ARCH=86 --tag $(LAGUNA_IMAGE) "$(LAGUNA_CONTEXT)"

push-laguna:
	docker buildx build --push --file .devops/cuda.Dockerfile --target server --build-arg CUDA_DOCKER_ARCH=86 --tag $(LAGUNA_IMAGE) "$(LAGUNA_CONTEXT)"

build-muse:
	docker build --file .devops/cuda.Dockerfile --target server --build-arg CUDA_DOCKER_ARCH=86 --tag $(MUSE_IMAGE) "$(MUSE_CONTEXT)"

push-muse:
	docker buildx build --push --file .devops/cuda.Dockerfile --target server --build-arg CUDA_DOCKER_ARCH=86 --tag $(MUSE_IMAGE) "$(MUSE_CONTEXT)"
