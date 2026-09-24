# Native Proxmox LXC deployment

This path runs **ntfy and NotifScheduler directly under systemd** in one Debian or Ubuntu LXC. Docker is not needed. Your existing Caddy LXC stays separate and proxies to ports 8093 (ntfy) and 8080 (scheduler) on the new container. The planned container IP is `192.168.0.144`; verify it before using the Caddy example.

## 1. Prepare the LXC

Create a Debian 12/13 or Ubuntu LXC with systemd, a persistent disk, and a static or reserved LAN IP. Make sure the Caddy LXC can reach the new container on TCP 8080 and 8093. Allow the new container outbound HTTPS to `ntfy.sh` for iOS push wakeups. Keep the Proxmox and container firewalls set so only the Caddy LXC can reach those two incoming ports.

Install Python and ntfy inside the **new** LXC. The commands below use [ntfy's official Debian/Ubuntu repository](https://docs.ntfy.sh/install/#debianubuntu-repository):

```sh
apt update
apt install -y ca-certificates curl gnupg apt-transport-https python3
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://archive.ntfy.sh/apt/keyring.gpg -o /etc/apt/keyrings/ntfy.gpg
gpg --show-keys --fingerprint /etc/apt/keyrings/ntfy.gpg
```

Check that the displayed fingerprint is `55BA 774A 6F5E E674 31E4 B6B7 CFDB 962D 4F1E C4AF`, as listed in the ntfy documentation. Then:

```sh
arch=$(dpkg --print-architecture)
echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/ntfy.gpg] https://archive.ntfy.sh/apt stable main" > /etc/apt/sources.list.d/ntfy.list
apt update
apt install -y ntfy
```

## 2. Install NotifScheduler

Copy or clone this project into the LXC, then run from the project directory as root:

```sh
bash lxc/install.sh
```

The installer copies the Python app to `/opt/notif-scheduler`, configures ntfy at `/etc/ntfy/server.yml`, creates a scheduler service account and SQLite data directory, generates a shared API key in `/etc/notif-scheduler/env`, and starts ntfy. It backs up the package's previous ntfy config to `/etc/ntfy/server.yml.before-notif-scheduler`. It deliberately waits to start the scheduler until a ntfy token is set.

## 3. Create ntfy accounts and start the scheduler

Run these commands **inside the new LXC**. They create an admin account for the iPhone and a write-only account for the scheduler. Each `user add` command prompts for a password.

```sh
runuser -u ntfy -- ntfy user add --role=admin admin
runuser -u ntfy -- ntfy user add scheduler
runuser -u ntfy -- ntfy access scheduler 'notif-*' write
runuser -u ntfy -- ntfy token add scheduler
```

Copy the resulting `tk_...` token into the `NTFY_TOKEN=` line of `/etc/notif-scheduler/env`, leaving the generated `SCHEDULER_API_KEY` intact. Keep this file readable only by root. Then start and check the service:

```sh
systemctl enable --now notif-scheduler
systemctl status ntfy notif-scheduler
curl http://127.0.0.1:8080/healthz
```

The health check should return `{"status":"ok"}`. It confirms the scheduler is running; a real notification test below confirms delivery.

## 4. Add the public Caddy route

Add the site block in [Caddyfile.example](Caddyfile.example) to your **existing Caddy LXC**, alongside the `foursevens.win` sites. Replace `192.168.0.144` if the new LXC gets another IP, then validate and reload Caddy there. Point `champyy.ddns.net` at your public IP, and forward public TCP 80 and 443 to the Caddy LXC. Your VPN can continue to use its existing port.

The ntfy app must be reachable at the root of `https://champyy.ddns.net`; the scheduler is under `/scheduler/`. The [iOS push setup](https://docs.ntfy.sh/config/#ios-instant-notifications) requires ntfy's `base-url` to match the URL used in the iOS app. The supplied config also sets `upstream-base-url: https://ntfy.sh` so iOS receives prompt wakeups.

## 5. Test an event from outside the LAN

On the iPhone, add `https://champyy.ddns.net` as the ntfy server, sign in as `admin`, allow notifications, and subscribe to `notif-backups`. Turn off Wi-Fi for the first test. From a shell on the new LXC:

```sh
api_key=$(sed -n 's/^SCHEDULER_API_KEY=//p' /etc/notif-scheduler/env)
curl -X POST 'https://champyy.ddns.net/scheduler/v1/projects/backups/events/failed' \
  -H "X-API-Key: ${api_key}"
```

The preset text comes from `/etc/notif-scheduler/events.json`. To change or add event names, edit that file and run `systemctl restart notif-scheduler`. The [main README](README.md#create-notifications) describes immediate, scheduled, and recurring API requests.

If delivery fails, inspect `journalctl -u notif-scheduler -u ntfy -n 100 --no-pager`. Check reachability from the Caddy LXC to both ports, and test `https://champyy.ddns.net` over cellular. If the iPhone only shows “New message,” it received the wakeup but could not fetch the actual message from your public server.

## Updates and backups

Back up `/var/lib/notif-scheduler`, `/var/lib/ntfy`, `/var/cache/ntfy`, `/etc/notif-scheduler`, and `/etc/ntfy/server.yml`. For an app code update, copy the new `scheduler.py` into `/opt/notif-scheduler` and restart `notif-scheduler`. Use the normal apt upgrade process for ntfy. The installer is for first setup and refuses to overwrite an existing installation.
