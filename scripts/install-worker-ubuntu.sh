#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$(id -u)" -ne 0 ]; then
  printf 'Run this installer as root.\n' >&2
  exit 1
fi

repo_dir="${1:-$PWD}"
if [ ! -f "$repo_dir/pyproject.toml" ]; then
  printf 'Usage: sudo scripts/install-worker-ubuntu.sh /path/to/tagged/cope-chess\n' >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates git python3 python3-pip python3-venv

id cope-worker >/dev/null 2>&1 || useradd --system --home-dir /var/lib/cope-worker --create-home --shell /usr/sbin/nologin cope-worker
install -d -o cope-worker -g cope-worker -m 0700 /var/lib/cope-worker
install -d -o root -g root -m 0755 /opt/cope-worker /etc/cope
python3 -m venv /opt/cope-worker/venv
/opt/cope-worker/venv/bin/python -m pip install --upgrade pip
/opt/cope-worker/venv/bin/python -m pip install "$repo_dir[worker]"
install -o root -g root -m 0644 "$repo_dir/deploy/cope-worker.service" /etc/systemd/system/cope-worker.service

if [ ! -f /etc/cope/worker.env ]; then
  install -o root -g root -m 0644 /dev/null /etc/cope/worker.env
  printf 'COPE_WORKER_SERVER_URL=wss://cope.example.com/worker\nCOPE_DEPLOY_COMMIT=replace-with-git-commit\n' > /etc/cope/worker.env
fi

systemctl daemon-reload
printf 'Worker runtime installed. Edit /etc/cope/worker.env, enroll the pool as cope-worker, then enable cope-worker.service.\n'
