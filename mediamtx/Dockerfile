ARG BUILD_FROM
FROM $BUILD_FROM

# shell + certs
RUN apk add --no-cache ca-certificates curl

# MediaMTX Version (kannst du später einfach hochdrehen)
ARG MEDIATEK_VERSION=v1.9.0
ARG TARGETARCH
ARG TARGETVARIANT

# Architektur-Mapping für bluenviron Releases
# amd64 -> linux_amd64
# aarch64 -> linux_arm64
# armv7 -> linux_armv7
RUN set -eux; \
  case "${TARGETARCH}${TARGETVARIANT}" in \
    "amd64")   ARCH="linux_amd64" ;; \
    "arm64")   ARCH="linux_arm64" ;; \
    "armv7")   ARCH="linux_armv7" ;; \
    *) echo "Unsupported arch: ${TARGETARCH}${TARGETVARIANT}" && exit 1 ;; \
  esac; \
  curl -fsSL -o /tmp/mediamtx.tar.gz "https://github.com/bluenviron/mediamtx/releases/download/${MEDIATEK_VERSION}/mediamtx_${MEDIATEK_VERSION#v}_${ARCH}.tar.gz"; \
  tar -xzf /tmp/mediamtx.tar.gz -C /usr/bin mediamtx; \
  chmod +x /usr/bin/mediamtx; \
  rm -f /tmp/mediamtx.tar.gz

COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8554 8888 8889 8890
CMD [ "/run.sh" ]
