FROM ghcr.io/jmrplens/cs-routeros-bouncer:latest

USER root

COPY run.sh /run.sh
RUN chmod +x /run.sh

ENTRYPOINT ["/run.sh"]
