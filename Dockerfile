ARG NODE_IMAGE=public.ecr.aws/docker/library/node:22-bookworm-slim
ARG PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.12-slim-bookworm
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG DEBIAN_MIRROR=mirrors.aliyun.com
FROM ${NODE_IMAGE} AS node-deps
WORKDIR /deps

FROM ${PYTHON_IMAGE} AS runtime
ARG PIP_INDEX_URL
ARG DEBIAN_MIRROR
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
    HOME=/home/scribe CLAUDE_CONFIG_DIR=/app/.scribe-runs/claude-config
RUN sed -i \
      -e "s@deb.debian.org@${DEBIAN_MIRROR}@g" \
      -e "s@security.debian.org@${DEBIAN_MIRROR}@g" \
      -e 's@http://@https://@g' \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git libstdc++6 libreoffice-writer fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 scribe \
    && useradd --uid 10001 --gid scribe --create-home scribe
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt
COPY --from=node-deps /usr/local/bin/node /usr/local/bin/node
COPY python/ ./python/
COPY .claude/ ./.claude/
COPY .mcp.json ./
# 本版本将数据库配置随镜像交付；/app/config 是容器内目录。
COPY --chown=10001:10001 --chmod=0400 config/databases.json ./config/databases.json
# Fixed /app paths are container-scoped; deployment helpers run from this image.
COPY deploy/entrypoint.py deploy/write-env.py deploy/smoke.py ./deploy/
# COPY 的 chmod 也作用于新建父目录；目录必须可进入，JSON 仍保持只读。
RUN chmod 0500 /app/config \
    && mkdir -p /app/.scribe-runs/claude-config && chown -R scribe:scribe /app/.scribe-runs
USER 10001:10001
RUN PYTHONPATH=python python -m data_access check-config
EXPOSE 4310
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4310/health', timeout=3)"
ENTRYPOINT ["python", "deploy/entrypoint.py"]

FROM runtime AS test
COPY deploy/ ./deploy/
RUN python -m unittest discover -s python/tests -t python -p 'test_*.py'
RUN python deploy/test_write_env.py && python deploy/test_build.py && python deploy/test_databases.py && sh -n deploy/build.sh && sh -n deploy/deploy.sh
