# Native Proxmox LXC deployment

This path runs **ntfy and NotifScheduler directly under systemd** in one Debian or Ubuntu LXC. Docker is not needed. Noti-Suite is at `192.168.0.40`; the Cloudflare Tunnel connector already runs there. Your existing Caddy LXC can keep serving its other sites.

## 1. Prepare the LXC

Create a Debian 12/13 or Ubuntu LXC with systemd, a persistent disk, and a static or reserved LAN IP. Allow the container outbound HTTPS to Cloudflare and `ntfy.sh` for tunnel traffic and iOS push wakeups. The tunnel connector uses loopback ports 8080 and 8093, so those ports do not need to be open to the Internet. Restrict LAN access to trusted machines if the services also listen on the LAN address.

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

## 4. Publish through Cloudflare Tunnel

Keep the existing `cloudflared` connector in **Noti-Suite**. In the same tunnel, publish `ntfy.foursevens.win` to `http://127.0.0.1:8093` and `scheduler.foursevens.win` to `http://127.0.0.1:8080`. Follow [ACCESS.md](ACCESS.md) for the exact settings and checks. No new inbound router ports are needed. `champyy.ddns.net` and your VPN remain unchanged. [Caddyfile.example](Caddyfile.example) is only for a later move of the connector to your Caddy LXC.

The ntfy app must be reachable at the root of `https://ntfy.foursevens.win`; the scheduler dashboard is at `https://scheduler.foursevens.win/`. The [iOS push setup](https://docs.ntfy.sh/config/#ios-instant-notifications) requires ntfy's `base-url` to match the URL used in the iOS app. The supplied config also sets `upstream-base-url: https://ntfy.sh` so iOS receives prompt wakeups.

## 5. Test an event from outside the LAN

On the iPhone, add `https://ntfy.foursevens.win` as the ntfy server, sign in as `admin`, allow notifications, and subscribe to `notif-backups`. Turn off Wi-Fi for the first test. From a shell on the new LXC:

```sh
api_key=$(sed -n 's/^SCHEDULER_API_KEY=//p' /etc/notif-scheduler/env)
curl -X POST 'https://scheduler.foursevens.win/v1/projects/backups/events/failed' \
  -H "X-API-Key: ${api_key}"
```

The preset text comes from `/etc/notif-scheduler/events.json`. To change or add event names, edit that file and run `systemctl restart notif-scheduler`. The [main README](README.md#create-notifications) describes immediate, scheduled, and recurring API requests.

If delivery fails, inspect `journalctl -u notif-scheduler -u ntfy -n 100 --no-pager`. Check both local service ports on Noti-Suite and test `https://ntfy.foursevens.win` over cellular. For a Cloudflare 502, use the [hop-by-hop checks](ACCESS.md#verify-each-hop). If the iPhone only shows “New message,” it received the wakeup but could not fetch the actual message from your public server.

## Updates and backups

Back up `/var/lib/notif-scheduler`, `/var/lib/ntfy`, `/var/cache/ntfy`, `/etc/notif-scheduler`, and `/etc/ntfy/server.yml`. For an app code update, copy the updated project directory to Noti-Suite and run `bash lxc/update.sh` there. This copies the scheduler and dashboard files and restarts the service; it leaves the database, API key, and event presets in place. The dashboard is at `https://scheduler.foursevens.win/`; enter the existing `SCHEDULER_API_KEY` from `/etc/notif-scheduler/env`. The key is kept in browser session storage until the tab session ends. Use the normal apt upgrade process for ntfy. The installer is for first setup and refuses to overwrite an existing installation.
