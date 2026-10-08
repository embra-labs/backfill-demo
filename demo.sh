#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Unique project: cleanup only touches containers/volume created by this run.
project="embra-backfill-$(date +%s)-$$"
compose=(docker compose -p "$project")
cleanup() { "${compose[@]}" down --volumes --remove-orphans >/dev/null; }
trap cleanup EXIT
"${compose[@]}" up --build --abort-on-container-exit --exit-code-from runner
