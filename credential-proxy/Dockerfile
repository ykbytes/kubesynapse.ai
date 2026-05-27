FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o /credential-proxy .

FROM scratch
COPY --from=builder /credential-proxy /credential-proxy
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
USER 1000:1000
EXPOSE 4001 4010 4003 8080 9090
ENTRYPOINT ["/credential-proxy"]
