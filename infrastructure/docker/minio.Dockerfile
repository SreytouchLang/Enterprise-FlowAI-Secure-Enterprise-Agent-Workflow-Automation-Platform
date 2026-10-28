# Upstream community images were withdrawn; build the pinned official source.
# Local synthetic-data development only. Production uses AWS S3.
FROM golang:1.25-bookworm AS builder
ARG MINIO_RELEASE=RELEASE.2025-10-15T17-29-55Z
RUN CGO_ENABLED=0 GOBIN=/out go install github.com/minio/minio@${MINIO_RELEASE}
RUN cp /go/pkg/mod/github.com/minio/minio@*/LICENSE /out/LICENSE
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home minio && mkdir -p /data && chown minio:minio /data
COPY --from=builder /out/minio /usr/local/bin/minio
COPY --from=builder /out/LICENSE /usr/share/doc/minio/LICENSE
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
