#!/usr/bin/env bash
# Allow Docker containers to reach Ollama on the host.
# Default Ollama binds 127.0.0.1 only; host-gateway traffic never hits it.
# Run once:  sudo bash scripts/configure-ollama-for-docker.sh
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Re-run with sudo." >&2
  exit 1
fi

mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_CONTEXT_LENGTH=16384"
EOF

systemctl daemon-reload
systemctl restart ollama
sleep 1
ss -tlnp | grep 11434 || true
echo "OK — Ollama should listen on 0.0.0.0:11434 with context 16384."
