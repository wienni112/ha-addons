ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /app

RUN apk add --no-cache \
    python3 \
    py3-pip \
    ca-certificates

COPY requirements.txt /app/
RUN python3 -m pip install --no-cache-dir --break-system-packages -r /app/requirements.txt

COPY app/ /app/app/
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
