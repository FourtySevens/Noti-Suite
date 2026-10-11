#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo 'Run this script as root inside the Noti-Suite LXC.' >&2
    exit 1
fi
if ! systemctl cat notif-scheduler.service >/dev/null 2>&1; then
    echo 'notif-scheduler.service is not installed; follow LXC.md first.' >&2
    exit 1
fi

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for asset in scheduler.py dashboard.html dashboard.css dashboard.js; do
    install -o root -g root -m 0644 "$source_dir/$asset" "/opt/notif-scheduler/$asset"
done
systemctl restart notif-scheduler
systemctl is-active --quiet notif-scheduler
echo 'Scheduler updated. Dashboard: https://ntfy.foursevens.win/scheduler/'
