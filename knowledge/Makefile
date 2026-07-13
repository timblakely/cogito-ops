REGISTRY ?= ghcr.io/timblakely
TAG ?= dev
IMAGE := $(REGISTRY)/knowledge:$(TAG)

.PHONY: build push test
build:
	docker build --tag $(IMAGE) .
push:
	docker buildx build --push --tag $(IMAGE) .
test:
	python -m unittest app.py
