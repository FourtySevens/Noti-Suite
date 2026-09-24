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

The supplied LXC and Compose configurations already set ntfy's `base-url` to `https://ntfy.foursevens.win` and `upstream-base-url` to `https://ntfy.sh`. Use the same public URL in the iOS app. After an iPhone receives a push wakeup, it fetches the actual notification through the tunnel. Test with Wi-Fi off.

## Existing VPN

Your VPN remains on `champyy.ddns.net` and its existing port. It is separate from the Cloudflare Tunnel; no VPN change is required for ntfy.

DDNS alone cannot make a blocked port reachable. A [DNS challenge](https://caddyserver.com/docs/automatic-https#dns-challenge) can obtain a certificate without open ports, but the Cloudflare Tunnel supplies the actual public traffic path.
