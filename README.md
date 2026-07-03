# Twingate Client Http Proxy

Userspace HTTP Proxy Docker image for the official Twingate Linux client — no `NET_ADMIN`, `/dev/net/tun`, or service key required. Includes a built-in Web UI (port `8080`) for configuration and status.

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

## Development Guide

### Build Locally

```bash
docker build -t twingate-client-http-proxy .
```
