REGISTRY ?= ghcr.io/timblakely
TAG ?= dev

PROXY_IMAGE := $(REGISTRY)/vllm-proxy:$(TAG)
OPENAI_IMAGE := $(REGISTRY)/vllm-openai:$(TAG)
LAGUNA_IMAGE := $(REGISTRY)/llama-laguna:$(TAG)
# Poolside PR #3, pinned to its single commit until it is merged into laguna.
LAGUNA_CONTEXT := https://github.com/rpw/llama.cpp.git?branch=patch-1&checksum=ffbd3e3f62cb32d0cbe9c496a9d57e19aef5677d

.PHONY: build-proxy push-proxy build-openai push-openai build-laguna push-laguna

build-proxy:
	docker build --tag $(PROXY_IMAGE) vllm-proxy

push-proxy:
	docker buildx build --push --tag $(PROXY_IMAGE) vllm-proxy

build-openai:
	docker build --tag $(OPENAI_IMAGE) vllm-openai

push-openai:
	docker buildx build --push --tag $(OPENAI_IMAGE) vllm-openai

build-laguna:
	docker build --file .devops/cuda.Dockerfile --target server --build-arg CUDA_DOCKER_ARCH=86 --tag $(LAGUNA_IMAGE) "$(LAGUNA_CONTEXT)"

push-laguna:
	docker buildx build --push --file .devops/cuda.Dockerfile --target server --build-arg CUDA_DOCKER_ARCH=86 --tag $(LAGUNA_IMAGE) "$(LAGUNA_CONTEXT)"
