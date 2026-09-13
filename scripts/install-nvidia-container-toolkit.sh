#!/usr/bin/env bash
# Install NVIDIA Container Toolkit so Docker can use the host GPU.
# Run once:  sudo bash scripts/install-nvidia-container-toolkit.sh
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Re-run with sudo." >&2
  exit 1
fi

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list

apt-get update
apt-get install -y nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

echo "OK — verify with:"
echo "  docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi -L"
