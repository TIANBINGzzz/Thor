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
set -- --build-arg "NODE_IMAGE=${NODE_IMAGE:-public.ecr.aws/docker/library/node:22-bookworm-slim}" \
    --build-arg "PYTHON_IMAGE=${PYTHON_IMAGE:-public.ecr.aws/docker/library/python:3.12-slim-bookworm}" \
    --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}" \
    --build-arg "DEBIAN_MIRROR=${DEBIAN_MIRROR:-mirrors.aliyun.com}"
docker build "$@" --target test --tag "${CCSDK_IMAGE}-test" .
docker build "$@" --target runtime --tag "$CCSDK_IMAGE" .
mkdir -p "$release_directory/deploy"
cp deploy/deploy.sh deploy/compose.yaml deploy/compose.database.yaml "$release_directory/deploy/"
printf '%s\n' "$CCSDK_IMAGE" > "$release_directory/image.ref"
docker image inspect --format '{{.Id}}' "$CCSDK_IMAGE" > "$release_directory/image.id"
docker save --output "$release_directory/image.tar" "$CCSDK_IMAGE"
(cd "$release_directory" && sha256sum image.tar image.ref image.id deploy/* > SHA256SUMS)
echo 'Image and deployment files ready for ArtifactUpload; no registry push required.'
