FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /out/vllm-proxy ./cmd/vllm-proxy

FROM gcr.io/distroless/static-debian13:nonroot AS proxy
COPY --from=build /out/vllm-proxy /vllm-proxy
USER nonroot:nonroot
ENTRYPOINT ["/vllm-proxy"]

# The cache manager needs the official Hugging Face CLI for gated and Xet
# downloads. It shares the same binary and source revision as the proxy.
FROM python:3.12-slim AS cache-manager
RUN pip install --no-cache-dir huggingface_hub==0.34.4 hf_xet
COPY --from=build /out/vllm-proxy /vllm-proxy
ENTRYPOINT ["/vllm-proxy", "cache-manager"]
