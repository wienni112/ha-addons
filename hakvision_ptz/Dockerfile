ARG BUILD_FROM=ghcr.io/hassio-addons/base-python:16.0.2
FROM ${BUILD_FROM}

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir --break-system-packages -r /app/requirements.txt

COPY app/ /app/app/
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
