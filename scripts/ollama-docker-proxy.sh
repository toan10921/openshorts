#!/usr/bin/env bash
# Proxy Ollama (127.0.0.1:11434) to 0.0.0.0:11435 so Docker can reach it
# without changing the systemd Ollama bind address.
# Prefer the permanent fix: sudo bash scripts/configure-ollama-for-docker.sh
set -euo pipefail
PORT="${OLLAMA_PROXY_PORT:-11435}"
if ss -tln | grep -q ":${PORT} "; then
  echo "Already listening on :${PORT}"
  exit 0
fi
exec socat TCP-LISTEN:"${PORT}",fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:11434
