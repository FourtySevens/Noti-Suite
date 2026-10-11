# Network diagram

```mermaid
flowchart LR
    Projects[Project machines<br/>and containers]
    Phone[iPhone<br/>ntfy app]
    Edge[Cloudflare Tunnel<br/>two public hostnames]
    Push[ntfy.sh<br/>push upstream]
    APNS[Apple Push<br/>wake-up delivery]

    subgraph Proxmox[Proxmox host / LAN]
        subgraph AppLXC[Noti-Suite LXC · 192.168.0.40]
            Tunnel[cloudflared<br/>outbound connector]
            API[Scheduler dashboard + API<br/>systemd · TCP 8080]
            Ntfy[ntfy server<br/>systemd · TCP 8093]
            Jobs[(Scheduler SQLite<br/>job queue)]
            NData[(ntfy SQLite<br/>auth and cache)]
            Tunnel -->|scheduler hostname| API
            Tunnel -->|ntfy hostname| Ntfy
            API -->|publish to 127.0.0.1:8093| Ntfy
            API --> Jobs
            Ntfy --> NData
        end
        Caddy[Existing Caddy LXC<br/>other sites]
    end

    Projects -->|HTTPS: scheduler.foursevens.win/v1/...| Edge
    Phone -->|HTTPS: ntfy.foursevens.win| Edge
    Tunnel -->|outbound connection| Edge
    Edge -->|requests over tunnel| Tunnel
    Ntfy -->|poll request; no message body| Push
    Push --> APNS
    APNS -->|wake-up| Phone
```

**Public URLs:** `https://ntfy.foursevens.win` serves ntfy topics and the ntfy web app. `https://scheduler.foursevens.win` serves the scheduler dashboard and `/v1/...` API. The existing Caddy sites and `champyy.ddns.net` VPN stay separate.

**Immediate event:** A machine posts an event name to the scheduler; the scheduler reads its preset from `events.json`, writes a job to SQLite, and publishes to the project's ntfy topic. Scheduled and recurring jobs use the same delivery path when due.

**iOS delivery:** ntfy sends a wake-up request through `ntfy.sh` and Apple Push Notification service. The iPhone then fetches the notification content through `ntfy.foursevens.win` and the tunnel. The ntfy upstream receives a poll request, not the notification body. The iPhone must be able to reach the public HTTPS URL outside the LAN.

**LAN access:** `cloudflared` runs on Noti-Suite and connects outward to Cloudflare. The two published application routes point to Noti-Suite's loopback ports 8093 and 8080. No inbound router forwarding is needed.
