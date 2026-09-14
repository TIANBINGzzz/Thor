#!/bin/sh
set -eu
set +x
: "${CCSDK_CONFIG_DIRECTORY:?Set a persistent host configuration directory}"
cd "$(dirname "$0")"
docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
compose_version=$(docker compose version --short)
case "$compose_version" in
    2.*|v2.*)
        minor=$(printf '%s' "$compose_version" | cut -d. -f2)
        [ "$minor" -ge 30 ] || { echo 'Docker Compose >=2.30 is required.' >&2; exit 1; } ;;
    [3-9].*|v[3-9].*) ;;
    *) echo 'Docker Compose >=2.30 is required.' >&2; exit 1 ;;
esac
umask 077
mkdir -p "$CCSDK_CONFIG_DIRECTORY"
config_directory=$(cd "$CCSDK_CONFIG_DIRECTORY" && pwd -P)
export CCSDK_CONFIG_DIRECTORY="$config_directory"
export CCSDK_ENV_FILE="${CCSDK_ENV_FILE:-$config_directory/runtime.env}"
export CCSDK_DATA_DIRECTORY="${CCSDK_DATA_DIRECTORY:-$config_directory/data}"
# Prevent two host deployment jobs from replacing the same service concurrently.
exec 9>"${CCSDK_DEPLOY_LOCK_FILE:-$config_directory/deploy.lock}"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
if [ -n "${CCSDK_RELEASE_DIRECTORY:-}" ]; then
    release_directory=$(cd "$CCSDK_RELEASE_DIRECTORY" && pwd -P)
    (cd "$release_directory" && sha256sum --check --status SHA256SUMS)
    release_image=$(cat "$release_directory/image.ref")
    if [ -n "${CCSDK_IMAGE:-}" ] && [ "$CCSDK_IMAGE" != "$release_image" ]; then
        echo 'CCSDK_IMAGE does not match the release manifest.' >&2; exit 1
    fi
    export CCSDK_IMAGE="$release_image"
    docker load --input "$release_directory/image.tar"
    [ "$(docker image inspect --format '{{.Id}}' "$CCSDK_IMAGE")" = "$(cat "$release_directory/image.id")" ] || {
        echo 'Loaded image does not match the release image ID.' >&2; exit 1;
    }
fi
: "${CCSDK_IMAGE:?Set the imported image or CCSDK_RELEASE_DIRECTORY}"
docker image inspect "$CCSDK_IMAGE" >/dev/null
if [ "${CCSDK_GENERATE_ENV:-0}" = 1 ]; then
    # /app and /config below are container paths. No host Python is required.
    set -- --rm --pull never --network none --user 0 --entrypoint python \
        --mount "type=bind,source=$config_directory,target=/config"
    if [ "${CCSDK_DEPLOY_ENV_B64+x}" = x ]; then
        set -- "$@" --env CCSDK_DEPLOY_ENV_B64
    else
        keys=$(docker run --rm --pull never --network none --entrypoint python \
            "$CCSDK_IMAGE" /app/deploy/write-env.py --list-keys)
        for key in $keys; do set -- "$@" --env "$key"; done
    fi
    set -- "$@" "$CCSDK_IMAGE" /app/deploy/write-env.py --directory /config
    if [ "${CCSDK_WITH_DATABASE:-0}" = 1 ]; then set -- "$@" --database; fi
    docker run "$@"
    export CCSDK_ENV_FILE="$config_directory/runtime.env"
    export CCSDK_DATA_DIRECTORY="$config_directory/data"
fi
set -- -f compose.yaml
if [ "${CCSDK_WITH_DATABASE:-0}" = 1 ]; then set -- "$@" -f compose.database.yaml; fi
docker compose "$@" config --quiet
docker compose "$@" run --rm --no-deps --pull never runtime --check
docker compose "$@" up -d --force-recreate --wait --wait-timeout 120 --pull never runtime
if [ "${CCSDK_SMOKE_TEST:-0}" = 1 ]; then
    docker compose "$@" exec -T runtime python /app/deploy/smoke.py
fi
echo 'Deployment healthy. Java/File Broker and business data acceptance remain separate checks.'
