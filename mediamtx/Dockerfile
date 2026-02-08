ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache ca-certificates curl tar

ARG MEDIATEK_VERSION=v1.15.6
ARG TARGETARCH
ARG TARGETVARIANT

RUN set -eux; \
  case "${TARGETARCH}${TARGETVARIANT}" in \
    "amd64") ARCH="linux_amd64" ;; \
    "arm64") ARCH="linux_arm64" ;; \
    "armv7") ARCH="linux_armv7" ;; \
    *) echo "Unsupported arch: ${TARGETARCH}${TARGETVARIANT}" && exit 1 ;; \
  esac; \
  VER="${MEDIATEK_VERSION#v}"; \
  URL="https://github.com/bluenviron/mediamtx/releases/download/${MEDIATEK_VERSION}/mediamtx_v${VER}_${ARCH}.tar.gz"; \
  echo "Downloading: ${URL}"; \
  curl -fL -o /tmp/mediamtx.tar.gz "${URL}"; \
  tar -xzf /tmp/mediamtx.tar.gz -C /usr/bin mediamtx; \
  chmod +x /usr/bin/mediamtx; \
  rm -f /tmp/mediamtx.tar.gz

COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8554 8888 8889
CMD ["/run.sh"]
