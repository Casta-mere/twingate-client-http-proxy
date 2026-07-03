# Twingate Client Http Proxy

Userspace HTTP Proxy Docker image for the official Twingate Linux client — no `NET_ADMIN`, `/dev/net/tun`, or service key required. Includes a built-in Web UI (port `8080`) for configuration, status, and generating a Clash rule provider + acceleration override.

[![Build and Push Docker Image](https://github.com/Casta-mere/twingate-client-http-proxy/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Casta-mere/twingate-client-http-proxy/actions/workflows/docker-image.yml)

## User Guide

### Docker Compose (recommended)

```bash
curl -o docker-compose.yaml https://raw.githubusercontent.com/Casta-mere/twingate-client-http-proxy/main/docker-compose.yaml
docker compose up -d
```

### Pull & Run

```bash
docker pull ghcr.io/casta-mere/twingate-client-http-proxy:latest

docker run -d --name twingate-client-http-proxy \
  -p 7575:9999 \
  -p 7576:8080 \
  ghcr.io/casta-mere/twingate-client-http-proxy:latest
```

### Web UI (recommended)

Open http://127.0.0.1:7576 in your browser.

<img width="326" height="338" alt="image" src="https://github.com/user-attachments/assets/8b4f0d2e-4bb7-414d-89a6-a10edec68d56" />

1. Enter your **Twingate network name** (e.g. `acme` for `acme.twingate.com`).
2. Click **Login** — this runs `twingate setup` and `twingate start` automatically.
3. The **Status** and **Resources** areas poll automatically every 2 seconds, showing `twingate status` and `twingate resources` output.
4. *(Optional, macOS)* Use the **Clash Acceleration Setup** card to generate a ready-to-paste Clash override that routes your resources through this proxy and accelerates the relay — see [Accelerating the data relay](#accelerating-the-data-relay-optional-macos).

### CLI (alternative)

```bash
# Setup (network name required)
docker exec -it twingate-client-http-proxy twingate setup

# Start (login)
docker exec -it twingate-client-http-proxy twingate start

# Check status
docker exec -it twingate-client-http-proxy twingate status

# List resources
docker exec -it twingate-client-http-proxy twingate resources

# Stop (logout)
docker exec -it twingate-client-http-proxy twingate stop
```

### Using the Proxy

Once the container is running, any client configured to use an HTTP proxy can connect:

```bash
curl --proxy http://127.0.0.1:7575 https://example.com
```

### Clash Integration

After login, a Clash rule file is automatically generated from your Twingate resources and served at:

```
http://127.0.0.1:7576/rule-twingate.yaml
```

Reference it as a [rule provider](https://wiki.metacubex.one/en/config/rule-providers/) in your Clash config pointing traffic to the proxy on port `7575`.

### Accelerating the data relay (optional, macOS)

Twingate's data tunnel reaches its relays over raw sockets that ignore HTTP proxies, so a slow China→overseas hop can't be sped up with a normal upstream proxy. On a **Mac running Docker Desktop** you can route that relay traffic through a fast Clash node instead:

1. Run this container **locally on your Mac** (Docker Desktop).
2. Turn on **Clash TUN mode** — required. Docker's backend (`com.docker.backend`) makes raw connections the system HTTP proxy can't see; only TUN mode can capture and route them.
3. In the Web UI, open the **Clash Acceleration Setup** card, tweak **Options** if needed, and click **Generate**.
4. Paste the result into your **Clash Party / mihomo global override**.

The generator auto-detects the live relay port range and your resource domains, and emits:

- a `twingate` HTTP proxy + `Twingate` group so the browser reaches resources through this container;
- a node group (`url-test` over nodes matched by a regex filter);
- the acceleration rule
  `AND,((PROCESS-NAME,com.docker.backend),(NETWORK,TCP),(DST-PORT,<lo-hi>)),<node>`
  (plus `(DOMAIN,…)` rules for any extra domains) that sends only the relay traffic through the node.

It's also available directly:

```
http://127.0.0.1:7576/clash-override.yaml?host=127.0.0.1&port=7575&node=Singapore&region=singapore&process=com.docker.backend&domains=
```

> **Platform note:** `com.docker.backend` is the macOS Docker Desktop process. Windows Docker Desktop differs; native Linux Docker has no such host process (the relay isn't attributable to one). This is a copy-paste generator — it never writes your Clash config.

## Development Guide

### Build Locally

```bash
docker build -t twingate-client-http-proxy .
```
