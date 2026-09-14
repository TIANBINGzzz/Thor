#!/bin/sh
set -eu
: "${CCSDK_IMAGE:?Set the exact image built by this release}"
: "${CCSDK_CONFIG_DIRECTORY:?Set a persistent host configuration directory}"
cd "$(dirname "$0")"
umask 077
mkdir -p "$CCSDK_CONFIG_DIRECTORY"
config_directory=$(cd "$CCSDK_CONFIG_DIRECTORY" && pwd -P)
export CCSDK_CONFIG_DIRECTORY="$config_directory"
export CCSDK_ENV_FILE="${CCSDK_ENV_FILE:-$config_directory/runtime.env}"
export CCSDK_DATABASE_ENV_FILE="${CCSDK_DATABASE_ENV_FILE:-$config_directory/database-qa.env}"
# Prevent two host deployment jobs from replacing the same service concurrently.
exec 9>"${CCSDK_DEPLOY_LOCK_FILE:-$config_directory/deploy.lock}"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
set -- -f compose.yaml
if [ "${CCSDK_WITH_DATABASE:-0}" = 1 ]; then
    set -- "$@" -f compose.database.yaml
fi
if [ "${CCSDK_GENERATE_ENV:-0}" = 1 ]; then
    if [ "${CCSDK_WITH_DATABASE:-0}" = 1 ]; then
        python3 write-env.py --directory "$config_directory" --database
    else
        python3 write-env.py --directory "$config_directory"
    fi
    export CCSDK_ENV_FILE="$config_directory/runtime.env"
    export CCSDK_DATABASE_ENV_FILE="$config_directory/database-qa.env"
fi
docker compose "$@" config --quiet
case "${CCSDK_PULL_IMAGE:-1}" in
    1) docker compose "$@" pull runtime ;;
    0) docker image inspect "$CCSDK_IMAGE" >/dev/null ;;
    *) echo 'CCSDK_PULL_IMAGE must be 0 or 1.' >&2; exit 1 ;;
esac
docker compose "$@" run --rm --no-deps runtime --check
docker compose "$@" up -d --force-recreate --wait --wait-timeout 120 runtime
echo 'HTTP health check passed; real JWT/model/MCP acceptance is still required.'
