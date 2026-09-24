# NotifScheduler

A small HTTP API for one-time, recurring, and event-triggered notifications. Machines and containers submit jobs; a persistent SQLite queue delivers them to a self-hosted [ntfy](https://docs.ntfy.sh/) server. A Cloudflare Tunnel through your existing Caddy LXC serves ntfy and the API at `https://ntfy.foursevens.win`.

**Recommended for Proxmox:** [run both services natively in one LXC](LXC.md). The Docker Compose deployment below remains available as an alternative. The API examples apply to either deployment.

See the [Cloudflare Tunnel setup](ACCESS.md) and [network diagram](NETWORK.md) for the public request path and iOS delivery flow. `champyy.ddns.net` stays dedicated to your VPN. No new router port forwarding is required.

## Docker Compose deployment (alternative)

### Before starting

- Configure a Cloudflare Tunnel in your Caddy LXC for `ntfy.foursevens.win`, following [ACCESS.md](ACCESS.md). Do not point this hostname at your home IP.
- Give the Docker host a stable LAN IP that the Caddy LXC can reach. The stack binds ntfy to port 8093 and the scheduler to port 8080 on that address. Restrict those two ports to the Caddy LXC in your firewall.
- Install Docker and the Compose plugin.

This setup makes ntfy and the scheduler API reachable from outside the LAN. The API requires one shared key for all projects. Keep that key private; anyone who has it can create, list, and cancel jobs in any project.

### Set up

1. Create the Docker host, reserve its LAN IP, and verify whether it is `192.168.0.144`. Copy `.env.example` to `.env`. Generate a key with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` and put it in `SCHEDULER_API_KEY`. Set `HOST_BIND_ADDRESS` to the verified IP. Do not commit `.env`.
2. Start ntfy: `docker compose up -d ntfy`.
3. Create an ntfy administrator for signing in on phones and the web app:

   ```sh
   docker compose exec ntfy ntfy user add --role=admin admin
   ```

   The command prompts for a password.
4. Create a dedicated ntfy account for the scheduler, grant it write access to project topics, and create a token:

   ```sh
   docker compose exec ntfy ntfy user add scheduler
   docker compose exec ntfy ntfy access scheduler 'notif-*' write
   docker compose exec ntfy ntfy token add scheduler
   ```

   Copy the `tk_...` token into `NTFY_TOKEN` in `.env`. The account's password can be a separate random password; the scheduler uses its token.
5. Start everything: `docker compose up -d --build`. Check `docker compose ps` and `docker compose logs --tail=100 scheduler ntfy`.
6. In your Caddy LXC, add the loopback listener from `Caddyfile.example` alongside your existing sites, using the verified Docker host IP. Reload Caddy, then publish `ntfy.foursevens.win` through Cloudflare Tunnel as described in [ACCESS.md](ACCESS.md).
7. On an iPhone, add `https://ntfy.foursevens.win` as the ntfy server, sign in as `admin`, allow notifications, and subscribe to a project topic such as `notif-backups`. Test while on cellular data. Each project gets a topic named `notif-<project>`.

The scheduler stores jobs in a named Docker volume. The ntfy user database and message cache use another named volume. Back up both volumes along with `.env` and your Caddy configuration.

## Create notifications

Send requests to `https://ntfy.foursevens.win/scheduler/v1/projects/<project>/notifications`. Project names use letters, digits, `_`, and `-` (up to 64 characters, including the `notif-` topic prefix). Use the same key for every project.

For the curl examples below, export `SCHEDULER_API_KEY` in your shell with the value from `.env`.

Send now:

```sh
curl -X POST 'https://ntfy.foursevens.win/scheduler/v1/projects/backups/notifications' \
  -H "X-API-Key: $SCHEDULER_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: backup-2026-09-24' \
  -d '{"title":"Backup complete","message":"NAS backup finished","priority":3,"tags":["white_check_mark"]}'
```

### Trigger a preset event immediately

Edit `events.json` (Compose) or `/etc/notif-scheduler/events.json` (LXC) to define each project's event names and notification contents. The included examples are `backups/completed` and `backups/failed`. Restart the scheduler after editing with `docker compose restart scheduler` or `systemctl restart notif-scheduler`, respectively.

```sh
curl -X POST 'https://ntfy.foursevens.win/scheduler/v1/projects/backups/events/failed' \
  -H "X-API-Key: $SCHEDULER_API_KEY" \
  -H 'Idempotency-Key: backup-failure-2026-09-24'
```

The caller provides the project and event name. The scheduler looks up the preset title, message, priority, and tags, then queues it for immediate delivery. Omit `Idempotency-Key` for events that should notify every time; provide a unique value per event occurrence to prevent duplicate requests from scheduling duplicate messages. The response contains a job ID and its current status.

Send once at a specific time (include a timezone):

```json
{"message":"Rotate the backup drive","send_at":"2026-10-01T09:00:00-04:00"}
```

Repeat every hour, starting at the given time:

```json
{"message":"Check the service dashboard","send_at":"2026-10-01T09:00:00-04:00","every_seconds":3600}
```

`send_at` defaults to now. `every_seconds` can be 60 through 31,536,000; a repeating job skips missed intervals if the server was down. The scheduler accepts messages up to 4,000 bytes. Priority is 1 through 5, with 3 as the default. `tags` is an optional list of ntfy tag names.

The API returns a job `id` and its status. `Idempotency-Key` is optional; reusing the same key for the same project returns the original job instead of scheduling a second one. Use a different key for each event or intended scheduled job.

List the latest 100 jobs, inspect one, or cancel a pending job:

```sh
curl -H "X-API-Key: $SCHEDULER_API_KEY" \
  'https://ntfy.foursevens.win/scheduler/v1/projects/backups/notifications'

curl -H "X-API-Key: $SCHEDULER_API_KEY" \
  'https://ntfy.foursevens.win/scheduler/v1/projects/backups/notifications/JOB_ID'

curl -X DELETE -H "X-API-Key: $SCHEDULER_API_KEY" \
  'https://ntfy.foursevens.win/scheduler/v1/projects/backups/notifications/JOB_ID'
```

`GET https://ntfy.foursevens.win/scheduler/healthz` is an unauthenticated liveness check. It does not check ntfy delivery. For a container on the `notif-scheduler` Docker network, `http://scheduler:8080/v1/...` also works; otherwise use the HTTPS address.

Delivery failures are retried with increasing delays, up to one hour between attempts. A job that was being sent when the scheduler stopped may be sent again after restart, so consumers should tolerate an occasional duplicate. Cancellation cannot recall a message already sent to ntfy.

## Security and operations

ntfy starts with anonymous access denied. The `admin` account can subscribe to all project topics; the `scheduler` account can only publish to `notif-*`. Your Caddy LXC terminates TLS for both ntfy and scheduler requests. The `SCHEDULER_API_KEY` travels in an HTTP header, so use the HTTPS URL from other machines. Rotate the shared key in `.env` (Compose) or `/etc/notif-scheduler/env` (LXC) and restart the scheduler if it leaks. ntfy tokens can be rotated separately.

Cloudflare Tunnel provides public reachability without inbound ports. Both deployments configure `upstream-base-url: https://ntfy.sh` so ntfy sends iOS push wakeups through ntfy.sh; the iPhone then fetches actual message content through the tunnel. Keep ntfy's public `base-url` identical to the server URL in the iOS app. If the phone only shows “New message,” verify that it can reach `https://ntfy.foursevens.win` outside your LAN. See the [ntfy iOS setup](https://docs.ntfy.sh/config/#ios-instant-notifications) and [known issues](https://docs.ntfy.sh/known-issues/).

Useful upstream references: [ntfy access control and reverse proxy settings](https://docs.ntfy.sh/config/), [ntfy publishing API](https://docs.ntfy.sh/publish/), [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https).
