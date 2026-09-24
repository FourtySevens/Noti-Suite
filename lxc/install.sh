#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo 'Run this script as root inside the LXC.' >&2
    exit 1
fi

for binary in ntfy python3 systemctl; do
    if ! command -v "$binary" >/dev/null 2>&1; then
        echo "Missing $binary. Install it first; see LXC.md." >&2
        exit 1
    fi
done

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

if [[ -e /etc/notif-scheduler/installed ]]; then
    echo 'LXC installation already exists; no files were overwritten.' >&2
    exit 1
fi

if ! id -u ntfy >/dev/null 2>&1; then
    echo 'The ntfy package did not create the ntfy user. Check the package installation.' >&2
    exit 1
fi

if ! getent group notif-scheduler >/dev/null; then
    groupadd --system notif-scheduler
fi
if ! id -u notif-scheduler >/dev/null 2>&1; then
    useradd --system --gid notif-scheduler --home-dir /var/lib/notif-scheduler \
        --shell /usr/sbin/nologin notif-scheduler
fi

install -d -o root -g root -m 0755 /opt/notif-scheduler
install -o root -g root -m 0644 "$source_dir/scheduler.py" /opt/notif-scheduler/scheduler.py
install -d -o notif-scheduler -g notif-scheduler -m 0750 /var/lib/notif-scheduler
install -d -o ntfy -g ntfy -m 0750 /var/lib/ntfy
install -d -o ntfy -g ntfy -m 0750 /var/cache/ntfy
install -d -o root -g notif-scheduler -m 0750 /etc/notif-scheduler
install -o root -g notif-scheduler -m 0640 "$source_dir/events.json" /etc/notif-scheduler/events.json

api_key=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
install -o root -g root -m 0600 /dev/null /etc/notif-scheduler/env
printf 'SCHEDULER_API_KEY=%s\nNTFY_TOKEN=\n' "$api_key" > /etc/notif-scheduler/env

if [[ -e /etc/ntfy/server.yml ]]; then
    cp -a /etc/ntfy/server.yml /etc/ntfy/server.yml.before-notif-scheduler
fi
install -o root -g root -m 0644 "$source_dir/lxc/ntfy-server.yml" /etc/ntfy/server.yml
install -o root -g root -m 0644 "$source_dir/lxc/notif-scheduler.service" /etc/systemd/system/notif-scheduler.service

systemctl daemon-reload
systemctl enable ntfy
systemctl restart ntfy
touch /etc/notif-scheduler/installed

echo 'ntfy is installed and started. Next: create ntfy users and a scheduler token.'
echo 'Follow the remaining steps in LXC.md before starting notif-scheduler.'
