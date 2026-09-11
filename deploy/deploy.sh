#!/bin/sh
set -eu
: "${CCSDK_IMAGE:?Set the exact image built by this release}"
cd "$(dirname "$0")"
# Prevent two host deployment jobs from replacing the same service concurrently.
exec 9>/var/lock/ccsdkscribe-deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
set -- -f compose.yaml
if [ "${CCSDK_WITH_DATABASE:-0}" = 1 ]; then
    set -- "$@" -f compose.database.yaml
fi
docker compose "$@" config --quiet
docker compose "$@" pull runtime
docker compose "$@" run --rm --no-deps runtime --check
docker compose "$@" up -d --wait --wait-timeout 120 runtime
echo 'HTTP health check passed; real JWT/model/MCP acceptance is still required.'
