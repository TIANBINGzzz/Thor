#!/bin/sh
set -eu
: "${CCSDK_IMAGE:?Set a local image name and unique release tag}"
cd "$(dirname "$0")/.."
docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
case "$(docker info --format '{{.OSType}}/{{.Architecture}}')" in
    linux/x86_64|linux/amd64) ;;
    *) echo 'This release requires a Linux amd64 Docker daemon.' >&2; exit 1 ;;
esac
# Always start with an empty release directory; never archive the checkout or env.
release_directory=${CCSDK_OUTPUT_DIRECTORY:-dist/release}
if [ -e "$release_directory" ]; then
    echo 'Release directory already exists; choose a new CCSDK_OUTPUT_DIRECTORY.' >&2
    exit 1
fi
node_image=${NODE_IMAGE:-public.ecr.aws/docker/library/node:22-bookworm-slim}
python_image=${PYTHON_IMAGE:-public.ecr.aws/docker/library/python:3.12-slim-bookworm}
pull_base() {
    attempt=1
    while :; do
        echo "Base image pull $attempt/3: $1"
        if docker pull --platform linux/amd64 "$1"; then
            return 0
        fi
        if [ "$attempt" -eq 3 ]; then
            echo 'Base image pull failed after 3 attempts. Check registry/CDN connectivity or configure an accessible NODE_IMAGE/PYTHON_IMAGE.' >&2
            return 1
        fi
        sleep "$((attempt * 10))"
        attempt=$((attempt + 1))
    done
}
started=$(date +%s)
pull_base "$node_image"
pull_base "$python_image"
echo "Base image pulls completed in $(($(date +%s) - started))s"
set -- --build-arg "NODE_IMAGE=$node_image" \
    --build-arg "PYTHON_IMAGE=$python_image" \
    --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}" \
    --build-arg "DEBIAN_MIRROR=${DEBIAN_MIRROR:-mirrors.aliyun.com}"
started=$(date +%s)
docker build --pull=false --progress=plain "$@" --target test --tag "${CCSDK_IMAGE}-test" .
echo "Test image build completed in $(($(date +%s) - started))s"
started=$(date +%s)
docker build --pull=false --progress=plain "$@" --target runtime --tag "$CCSDK_IMAGE" .
echo "Runtime image build completed in $(($(date +%s) - started))s"
mkdir -p "$release_directory/deploy"
cp deploy/deploy.sh deploy/compose.yaml deploy/compose.database.yaml "$release_directory/deploy/"
printf '%s\n' "$CCSDK_IMAGE" > "$release_directory/image.ref"
docker image inspect --format '{{.Id}}' "$CCSDK_IMAGE" > "$release_directory/image.id"
started=$(date +%s)
docker save --output "$release_directory/image.tar" "$CCSDK_IMAGE"
(cd "$release_directory" && sha256sum image.tar image.ref image.id deploy/* > SHA256SUMS)
echo "Image export and checksums completed in $(($(date +%s) - started))s"
echo 'Image and deployment files ready for ArtifactUpload; no registry push required.'
