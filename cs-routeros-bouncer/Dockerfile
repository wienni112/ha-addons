ARG BUILD_FROM=ghcr.io/hassio-addons/base:17.2.3

FROM ghcr.io/jmrplens/cs-routeros-bouncer:latest AS upstream

FROM ${BUILD_FROM}

COPY --from=upstream / /opt/upstream
COPY run.sh /run.sh

RUN chmod +x /run.sh && \
    find /opt/upstream -type f -name "cs-routeros-bouncer" -exec cp {} /usr/local/bin/cs-routeros-bouncer \; && \
    chmod +x /usr/local/bin/cs-routeros-bouncer

CMD ["/run.sh"]
