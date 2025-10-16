#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHART_DIR="${SCRIPT_DIR}/chart"
OUTPUT_DIR="${SCRIPT_DIR}/resources"

mkdir -p "${OUTPUT_DIR}"

helm template rendered "${CHART_DIR}" \
  --namespace dev-bios-bechtle \
  --output-dir "${OUTPUT_DIR}"
