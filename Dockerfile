ARG NODE_IMAGE=crpi-0xufclpa0j3y3dn0.cn-shanghai.personal.cr.aliyuncs.com/ai_agent_python/node:22-bookworm-slim
ARG PYTHON_IMAGE=crpi-0xufclpa0j3y3dn0.cn-shanghai.personal.cr.aliyuncs.com/ai_agent_python/python:3.12-slim-bookworm
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG DEBIAN_MIRROR=mirrors.aliyun.com
FROM ${NODE_IMAGE} AS node-deps
WORKDIR /deps

FROM ${PYTHON_IMAGE} AS document-base
ARG DEBIAN_MIRROR
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
    HOME=/home/scribe CLAUDE_CONFIG_DIR=/app/.scribe-runs/claude-config
COPY deploy/bookworm-backports.sources /etc/apt/sources.list.d/backports.sources
RUN sed -i \
      -e "s@deb.debian.org@${DEBIAN_MIRROR}@g" \
      -e "s@security.debian.org@${DEBIAN_MIRROR}@g" \
      -e 's@http://@https://@g' \
      /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/backports.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git curl libstdc++6 fonts-noto-cjk fonts-liberation2 \
    && apt-get install -y --no-install-recommends -t bookworm-backports libreoffice-writer python3-uno \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 scribe \
    && useradd --uid 10001 --gid scribe --create-home scribe
COPY deploy/cjk-fonts.conf /etc/fonts/conf.d/99-scribe-cjk.conf

# Windows本地开发复用此无桌面的渲染目标；Linux运行时直接继承相同引擎和字体。
FROM document-base AS document-renderer
COPY python/tools/document_conversion.py /opt/scribe/document_conversion.py
USER 10001:10001
ENTRYPOINT ["python", "/opt/scribe/document_conversion.py"]

FROM document-base AS runtime
ARG PIP_INDEX_URL
WORKDIR /app
# 随源码交付固定版本，构建不访问GitHub；仍核验上游哈希。路径仅属于容器。
COPY deploy/vendor/officecli/officecli-linux-x64 /usr/local/bin/officecli
COPY deploy/vendor/officecli/LICENSE /usr/local/share/licenses/officecli/LICENSE
RUN echo "8e2512234ae1111e51ad3a9fadbdeca266adfa7f683773469aa45b83fe06dc7f  /usr/local/bin/officecli" | sha256sum -c - \
    && chmod +x /usr/local/bin/officecli
ENV OFFICECLI_SKIP_UPDATE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt
COPY --from=node-deps /usr/local/bin/node /usr/local/bin/node
COPY python/ ./python/
COPY .claude/ ./.claude/
COPY .mcp.json ./
COPY --chown=10001:10001 --chmod=0400 config/application.yml ./config/application.yml
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
