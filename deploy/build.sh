#!/bin/sh
set -eu
: "${CCSDK_IMAGE:?Set the registry/repository and immutable release tag}"
cd "$(dirname "$0")/.."
set -- --build-arg "NODE_IMAGE=${NODE_IMAGE:-node:22-bookworm-slim}" \
    --build-arg "PYTHON_IMAGE=${PYTHON_IMAGE:-python:3.12-slim-bookworm}"
docker build "$@" --target test --tag "${CCSDK_IMAGE}-test" .
docker build "$@" --target runtime --tag "$CCSDK_IMAGE" .
docker run --rm --network none --entrypoint python \
    --mount "type=bind,source=$(pwd)/deploy,target=/checks,readonly" \
    "$CCSDK_IMAGE" /checks/test_write_env.py
# Registry login is owned by the pipeline service connection.
docker push "$CCSDK_IMAGE"
