#!/usr/bin/env bash
# Detached runner so the loop keeps going after this shell and the agent turn end.
cd "$(dirname "$0")"
mkdir -p state
exec setsid nohup ./loop.sh "${1:-10}" >> state/loop.out 2>&1 < /dev/null
