# Network diagram

```mermaid
flowchart LR
    Projects[Project machines<br/>and containers]
    Phone[iPhone<br/>ntfy app]
    DNS[champyy.ddns.net<br/>DDNS record]
    Router[Home router<br/>public IP]
    VPN[Existing VPN service]
    Push[ntfy.sh<br/>push upstream]
    APNS[Firebase / Apple Push<br/>wake-up delivery]

    subgraph Proxmox[Proxmox host / LAN]
        Caddy[Caddy LXC<br/>existing reverse proxy]
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

    Projects -->|HTTPS: event or scheduled request| DNS
    Phone -->|HTTPS: subscribe / fetch message| DNS
    DNS -.->|resolves to| Router
    Router -->|TCP 80 / 443 forwarded| Caddy
    Router -->|existing VPN port| VPN
    Caddy -->|/scheduler/* → TCP 8080| API
    Caddy -->|other paths → TCP 8093| Ntfy
    Ntfy -->|poll request; no message body| Push
    Push --> APNS
    APNS -->|wake-up| Phone
```

**Public URL:** `https://champyy.ddns.net` serves ntfy. The scheduler API is at `https://champyy.ddns.net/scheduler/v1/...`. Caddy keeps the existing `foursevens.win` sites in separate site blocks.

**Immediate event:** A machine posts an event name to the scheduler; the scheduler reads its preset from `events.json`, writes a job to SQLite, and publishes to the project's ntfy topic. Scheduled and recurring jobs use the same delivery path when due.

**iOS delivery:** ntfy sends a wake-up request through `ntfy.sh` and Apple Push Notification service. The iPhone then fetches the notification content directly from `champyy.ddns.net`. The ntfy upstream receives a poll request, not the notification body. The iPhone must be able to reach the public HTTPS URL outside the LAN.

**LAN access:** Only the Caddy LXC needs inbound access to ports 8080 and 8093 on the new LXC. Project clients can call the public HTTPS API. If local clients cannot reach the public IP from inside the LAN, use local DNS to resolve `champyy.ddns.net` to the Caddy LXC's LAN IP.
