ARG BUILD_FROM=ghcr.io/hassio-addons/base:17.2.3
FROM ${BUILD_FROM}

ARG TARGETARCH

RUN apk add --no-cache curl tar

RUN case "${TARGETARCH}" in \
      amd64) ARCH="amd64" ;; \
      aarch64) ARCH="arm64" ;; \
      armv7) ARCH="armv7" ;; \
      *) echo "Unsupported arch: ${TARGETARCH}" && exit 1 ;; \
    esac && \
    curl -L -o /tmp/cs-routeros-bouncer.tar.gz \
      "https://github.com/jmrplens/cs-routeros-bouncer/releases/latest/download/cs-routeros-bouncer_linux_${ARCH}.tar.gz" && \
    tar -xzf /tmp/cs-routeros-bouncer.tar.gz -C /tmp && \
    find /tmp -name cs-routeros-bouncer -type f -exec mv {} /usr/local/bin/cs-routeros-bouncer \; && \
    chmod +x /usr/local/bin/cs-routeros-bouncer && \
    rm -rf /tmp/*

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
