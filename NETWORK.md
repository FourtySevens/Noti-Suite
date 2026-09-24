# Network diagram

```mermaid
flowchart LR
    Projects[Project machines<br/>and containers]
    Phone[iPhone<br/>ntfy app]
    Edge[Cloudflare<br/>ntfy.foursevens.win]
    Push[ntfy.sh<br/>push upstream]
    APNS[Firebase / Apple Push<br/>wake-up delivery]

    subgraph Proxmox[Proxmox host / LAN]
        subgraph ProxyLXC[Existing Caddy LXC]
            Tunnel[cloudflared<br/>outbound tunnel]
            Caddy[Caddy<br/>127.0.0.1:8081]
            Tunnel --> Caddy
        end
        subgraph AppLXC[NotifScheduler LXC · planned 192.168.0.144]
            API[Scheduler API + worker<br/>systemd · TCP 8080]
            Ntfy[ntfy server<br/>systemd · TCP 8093]
            Jobs[(Scheduler SQLite<br/>job queue)]
            NData[(ntfy SQLite<br/>auth and cache)]
            API -->|publish to 127.0.0.1:8093| Ntfy
            API --> Jobs
            Ntfy --> NData
        end
    end

    Projects -->|HTTPS: event or scheduled request| Edge
    Phone -->|HTTPS: subscribe / fetch message| Edge
    Tunnel -->|outbound connection| Edge
    Edge -->|requests over tunnel| Tunnel
    Caddy -->|/scheduler/* → TCP 8080| API
    Caddy -->|other paths → TCP 8093| Ntfy
    Ntfy -->|poll request; no message body| Push
    Push --> APNS
    APNS -->|wake-up| Phone
```

**Public URL:** `https://ntfy.foursevens.win` serves ntfy through Cloudflare Tunnel. The scheduler API is at `https://ntfy.foursevens.win/scheduler/v1/...`. The existing `foursevens.win` Caddy sites and `champyy.ddns.net` VPN remain separate.

**Immediate event:** A machine posts an event name to the scheduler; the scheduler reads its preset from `events.json`, writes a job to SQLite, and publishes to the project's ntfy topic. Scheduled and recurring jobs use the same delivery path when due.

**iOS delivery:** ntfy sends a wake-up request through `ntfy.sh` and Apple Push Notification service. The iPhone then fetches the notification content through `ntfy.foursevens.win` and the tunnel. The ntfy upstream receives a poll request, not the notification body. The iPhone must be able to reach the public HTTPS URL outside the LAN.

**LAN access:** Only the Caddy LXC needs inbound access to ports 8080 and 8093 on the new LXC. Project clients call the public HTTPS API. No new inbound router forwarding is needed; `cloudflared` connects outward to Cloudflare.
