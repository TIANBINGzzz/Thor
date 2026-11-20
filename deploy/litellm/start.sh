#!/bin/sh
set -eu

# 通过 docker exec 的标准输入把两把密钥写进容器 tmpfs。
i=0
while [ ! -s /run/yyapi/credentials ]; do
    [ "$i" -lt 30 ] || exit 1
    i=$((i + 1))
    sleep 1
done
{
    IFS= read -r YYAPI_UPSTREAM_KEY
    IFS= read -r YYAPI_GATEWAY_KEY
} < /run/yyapi/credentials
rm /run/yyapi/credentials
: "${YYAPI_UPSTREAM_KEY:?}" "${YYAPI_GATEWAY_KEY:?}"
export YYAPI_UPSTREAM_KEY YYAPI_GATEWAY_KEY
exec litellm --config /etc/litellm/proxy.yml --host 0.0.0.0 --port 4000 --num_workers 1 \
    --ssl_certfile_path /run/yyapi/server.crt --ssl_keyfile_path /run/yyapi/server.key
