REGISTRY ?= ghcr.io/timblakely
TAG ?= dev

PROXY_IMAGE := $(REGISTRY)/vllm-proxy:$(TAG)
OPENAI_IMAGE := $(REGISTRY)/vllm-openai:$(TAG)

.PHONY: build-proxy push-proxy build-openai push-openai

build-proxy:
	docker build --tag $(PROXY_IMAGE) vllm-proxy

push-proxy:
	docker buildx build --push --tag $(PROXY_IMAGE) vllm-proxy

build-openai:
	docker build --tag $(OPENAI_IMAGE) vllm-openai

push-openai:
	docker buildx build --push --tag $(OPENAI_IMAGE) vllm-openai
