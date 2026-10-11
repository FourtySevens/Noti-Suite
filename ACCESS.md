# Cloudflare Tunnel public access

Your ISP blocks inbound TCP 80 and 443. Keep the Cloudflare Tunnel connector on **Noti-Suite**, where it is already running. One tunnel can publish both services under separate hostnames. No router port forwarding or Caddy change is needed for this setup. `champyy.ddns.net` stays dedicated to the VPN.

## Published application routes

In the [Cloudflare dashboard](https://developers.cloudflare.com/tunnel/get-started/#publish-an-application), go to **Networking → Tunnels**, select the existing tunnel, then add or edit its **Published application** routes:

| Public hostname | Service URL | Service |
| --- | --- | --- |
| `ntfy.foursevens.win` | `http://127.0.0.1:8093` | ntfy web, topics, iOS message fetches |
| `scheduler.foursevens.win` | `http://127.0.0.1:8080` | Scheduler dashboard and `/v1/...` API |

Use **HTTP** for both local Service URLs. They are loopback addresses on **Noti-Suite**, because that is where `cloudflared` runs. Cloudflare serves the public HTTPS certificates. A hostname alone is not a valid Service URL. Neither route needs a path prefix.

The scheduler URL must be separate from ntfy's hostname. ntfy interprets paths on `ntfy.foursevens.win` as topics; requests for `/scheduler/` will reach ntfy unless a separate proxy handles that path. Update scripts and containers to call `https://scheduler.foursevens.win/v1/...`. Keep the iOS ntfy app pointed at `https://ntfy.foursevens.win`.

The scheduler API requires the shared `SCHEDULER_API_KEY` in the `X-API-Key` header. The dashboard asks for that same key and stores it in browser session storage for the tab. Keep ntfy's own login and access controls enabled. A Cloudflare Access browser login in front of the ntfy hostname may interfere with native ntfy clients; the provided setup uses ntfy authentication and the scheduler API key.

## Verify each hop

On **Noti-Suite**:

```sh
systemctl is-active ntfy notif-scheduler cloudflared
curl -i http://127.0.0.1:8093/
curl -i http://127.0.0.1:8080/healthz
curl -i http://127.0.0.1:8080/
```

The first web request should return ntfy's page. The scheduler health request should return `{"status":"ok"}`, and its root should return the dashboard HTML. From a browser outside the LAN, open `https://ntfy.foursevens.win/` and `https://scheduler.foursevens.win/`. Test ntfy from the iPhone with Wi-Fi off.

If a public route returns 502 while the matching local request works, check that its Published application Service URL matches the table and that `cloudflared` is active on Noti-Suite. If the scheduler hostname shows ntfy's topic UI, that hostname is still routed to port 8093 or another ntfy proxy; change its Service URL to port 8080. `cloudflared tunnel list` asks for an account `cert.pem` even when a token-installed tunnel is serving traffic; use the Cloudflare dashboard or `systemctl is-active cloudflared` to check this connector.

## If the connector moves to Caddy later

The optional [Caddyfile.example](Caddyfile.example) provides two loopback listeners on the **Caddy LXC**. Once both listener checks work there, change the Cloudflare routes to `http://127.0.0.1:8081` for ntfy and `http://127.0.0.1:8082` for the scheduler, then install the tunnel connector on Caddy. Do not leave replicas of the same tunnel running in both LXCs with these loopback Service URLs: Cloudflare could send a request to either connector, and `127.0.0.1` would refer to different machines.

## iOS and VPN

The supplied ntfy config keeps `base-url: https://ntfy.foursevens.win` and `upstream-base-url: https://ntfy.sh`. The iPhone uses the ntfy hostname to fetch notification contents after a push wakeup. The scheduler hostname is for creating and managing notifications. Your VPN continues to use `champyy.ddns.net` independently.
