# Cloudflare Tunnel public access

Your ISP blocks inbound TCP 80 and 443. Use **Cloudflare Tunnel** with the Cloudflare-managed `foursevens.win` DNS zone. This makes `https://ntfy.foursevens.win` reachable from iPhones and project clients without any new router forwarding. Keep `champyy.ddns.net` for the existing VPN.

## Traffic path

Run `cloudflared` in the existing Caddy LXC. It opens an outbound connection to Cloudflare. Cloudflare accepts HTTPS requests for `ntfy.foursevens.win` and sends them through that tunnel to Caddy's loopback listener on port 8081. Caddy proxies `/scheduler/*` to the scheduler LXC on port 8080 and all other paths to ntfy on port 8093. The router needs **no new inbound forwarding**.

## Configure the Caddy LXC

Add the listener in [Caddyfile.example](Caddyfile.example) to your existing Caddy configuration, with the verified IP of the new application LXC. Caddy listens only on `127.0.0.1:8081` for tunnel traffic. Validate and reload Caddy on that LXC. Its existing `foursevens.win` routes can remain in place.

## Create the tunnel

In the [Cloudflare dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/), open **Networking → Tunnels**, create a tunnel, and select the Caddy LXC's Linux architecture. Run the installation command shown by Cloudflare **inside the Caddy LXC**; it installs `cloudflared` with that tunnel's token. Treat the token as a secret.

Add a **Published application** route with:

| Setting | Value |
| --- | --- |
| Subdomain | `ntfy` |
| Domain | `foursevens.win` |
| Service type | `HTTP` |
| Service URL | `http://127.0.0.1:8081` |

Wait for the tunnel to report healthy and check `https://ntfy.foursevens.win` on cellular. Cloudflare manages the public hostname and certificate. Keep ntfy's own login and access controls enabled. A Cloudflare Access browser login in front of this hostname may interfere with native ntfy clients, so this setup relies on ntfy authentication and the scheduler API key.

The connector must run in the **Caddy LXC** for the `127.0.0.1:8081` Service URL to work. If another connector for the same tunnel also runs in Noti-Suite, stop that instance after confirming the Caddy connector is healthy; Cloudflare can route requests to either connector. `cloudflared tunnel list` is a management command and may ask for an account `cert.pem` even when a token-installed tunnel service is running normally. Check tunnel health in the Cloudflare dashboard or use `systemctl is-active cloudflared` on the connector host. Do not share the tunnel installation token.

If the tunnel was first installed in Noti-Suite, move the connector in this order:

1. In the **Caddy LXC**, make sure `curl -i http://127.0.0.1:8081/` returns the ntfy page. Caddy's upstream must be `192.168.0.40:8093`, the actual Noti-Suite address.
2. In the Cloudflare dashboard, open **Networking → Tunnels → your existing tunnel → Overview → Add a replica**. Select Linux and copy the connector installation command. Run it in the **Caddy LXC**. Set the Published application's Service URL to `http://127.0.0.1:8081`. Keep the installation token private.
3. Confirm the tunnel has a healthy connector in the Caddy LXC and the public ntfy URL works. If the old connector in **Noti-Suite** is dedicated to this tunnel, stop it with `systemctl disable --now cloudflared`. If it also serves other routes, migrate those routes first or use a separate tunnel. Running both as replicas can send some requests to the wrong LXC.

The `cert.pem` requested by `cloudflared tunnel list` is an account management credential. A remotely managed tunnel installed with the dashboard token does not need it to serve traffic; it is separate from the TLS certificate Cloudflare presents to visitors.

The supplied LXC and Compose configurations already set ntfy's `base-url` to `https://ntfy.foursevens.win` and `upstream-base-url` to `https://ntfy.sh`. Use the same public URL in the iOS app. After an iPhone receives a push wakeup, it fetches the actual notification through the tunnel. Test with Wi-Fi off.

## If Cloudflare returns 502

The public TLS certificate is served by Cloudflare. The tunnel's **Service URL must be `http://127.0.0.1:8081` when `cloudflared` runs in the Caddy LXC**. It must use `http://`, because the example Caddy listener on port 8081 is plain HTTP. A Cloudflare Tunnel 502 usually means the connector cannot reach that local service; a 502 returned by Caddy instead points to one of its upstreams.

Run these on the **Caddy LXC**:

```sh
systemctl status cloudflared caddy --no-pager
curl -i http://127.0.0.1:8081/
curl -i http://192.168.0.40:8093/
curl -i http://192.168.0.40:8080/healthz
journalctl -u cloudflared -u caddy -n 100 --no-pager
```

Noti-Suite currently uses `192.168.0.40`; update these probes if its IP changes. Do not use `127.0.0.1:8093` from the Caddy LXC: loopback would point to Caddy's own container, while ntfy runs in Noti-Suite. An HTTP response from ntfy, including a login or authorization response, confirms that the port is reachable. The scheduler health URL should return `{"status":"ok"}`.

- If `127.0.0.1:8081` refuses connections, the Caddy listener was not added or reloaded. Validate your Caddy config and restart or reload Caddy.
- If port 8081 responds with a Caddy 502, check the two `192.168.0.40` probes, service status on the application LXC, and firewalls between the LXCs.
- If port 8081 works but the public URL still shows a Cloudflare 502, check the tunnel's Service URL and where `cloudflared` is installed. `127.0.0.1` always means the machine running `cloudflared`. Inspect its logs for `connection refused` or a protocol mismatch.

## Existing VPN

Your VPN remains on `champyy.ddns.net` and its existing port. It is separate from the Cloudflare Tunnel; no VPN change is required for ntfy.

DDNS alone cannot make a blocked port reachable. A [DNS challenge](https://caddyserver.com/docs/automatic-https#dns-challenge) can obtain a certificate without open ports, but the Cloudflare Tunnel supplies the actual public traffic path.
