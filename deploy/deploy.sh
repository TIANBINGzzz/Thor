#!/bin/sh
set -eu
set +x
: "${CCSDK_CONFIG_DIRECTORY:?Set a persistent host configuration directory}"
if [ "${CCSDK_SMOKE_TEST:-0}" = 1 ]; then
    : "${CCSDK_SMOKE_TENANT:?Set an explicit smoke test identity}"
fi
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
application_file=${CCSDK_APPLICATION_FILE:-$config_directory/application.production.yml}
[ -f "$application_file" ] || { echo "Missing application.production.yml." >&2; exit 1; }
application_parent=$(cd "$(dirname "$application_file")" && pwd -P)
export CCSDK_APPLICATION_FILE="$application_parent/$(basename "$application_file")"
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

set -- -f compose.yaml
docker compose "$@" config --quiet
docker compose "$@" run --rm --no-deps --pull never runtime --check
docker compose "$@" up -d --force-recreate --wait --wait-timeout 120 --pull never runtime
container_id=$(docker compose "$@" ps -q runtime)
[ -n "$container_id" ] || { echo 'Runtime container was not created.' >&2; exit 1; }
init_enabled=$(docker inspect --format '{{if .Config.Init}}true{{else}}false{{end}}' "$container_id")
pids_limit=$(docker inspect --format '{{.HostConfig.PidsLimit}}' "$container_id")
memory_limit=$(docker inspect --format '{{.HostConfig.Memory}}' "$container_id")
[ "$init_enabled" = true ] || { echo 'Runtime container must use an init process.' >&2; exit 1; }
[ "$pids_limit" -gt 0 ] || { echo 'Runtime container must have a positive PID limit.' >&2; exit 1; }
[ "$memory_limit" -gt 0 ] || { echo 'Runtime container must have a positive memory limit.' >&2; exit 1; }
if [ "${CCSDK_SMOKE_TEST:-0}" = 1 ]; then
    docker compose "$@" exec -T runtime python /app/deploy/smoke.py \
        --tenant "${CCSDK_SMOKE_TENANT:?Set an explicit smoke test identity}" \
        --domain-name "${CCSDK_SMOKE_DOMAIN_NAME:?Set the smoke test school domain}"
fi
echo 'Deployment healthy. Java file authorization and business data acceptance remain separate checks.'
