#!/usr/bin/env bash
# Render + build every starter template inside its CI container.
#
# Mirrors the `starters` stage in .gitlab-ci.yml, so you can reproduce the
# cross-language pipeline locally with only Docker installed (no gradle/cmake/jdk
# needed on the host). Run from anywhere: `scripts/check-starters.sh`.
set -euo pipefail

cd "$(dirname "$0")/.."

UV_INSTALL='curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH="$HOME/.local/bin:$PATH"'

run() {
  local name="$1" image="$2" cmd="$3"
  echo "=================================================================="
  echo "  $name  ($image)"
  echo "=================================================================="
  docker run --rm -v "$PWD:/work" -w /work "$image" bash -euo pipefail -c "$cmd"
}

run python "ghcr.io/astral-sh/uv:python3.13-bookworm-slim" \
  "uv run pytest -m integration -k python -v"

run java "gradle:8.7-jdk21" \
  "$UV_INSTALL && uv sync --frozen && uv run pytest -m integration -k java -v"

run cpp "gcc:13" \
  "apt-get update && apt-get install -y --no-install-recommends curl cmake git && \
   $UV_INSTALL && uv sync --frozen && uv run pytest -m integration -k cpp -v"

echo
echo "All starters rendered, built, and tested successfully."
