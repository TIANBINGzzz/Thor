ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}

RUN pip install --no-cache-dir 'litellm[proxy]==1.110.2' && pip check
USER 10001:10001
ENV HOME=/tmp PYTHONUNBUFFERED=1 LITELLM_LOCAL_MODEL_COST_MAP=True LITELLM_MODE=PRODUCTION LITELLM_TELEMETRY=False DO_NOT_TRACK=1 LITELLM_LOG=ERROR
COPY proxy.yml /etc/litellm/proxy.yml
COPY start.sh /usr/local/bin/start-yyapi-proxy

ENTRYPOINT ["/bin/sh", "/usr/local/bin/start-yyapi-proxy"]
