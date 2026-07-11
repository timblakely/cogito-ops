FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /out/vllm-proxy ./cmd/vllm-proxy

FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=build /out/vllm-proxy /vllm-proxy
USER nonroot:nonroot
ENTRYPOINT ["/vllm-proxy"]
