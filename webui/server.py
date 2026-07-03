#!/usr/bin/env python3
import datetime
import http.server
import json
import os
import re
import subprocess
import urllib.parse

WEBUI_ADDR = os.environ.get('WEBUI_ADDR', '0.0.0.0:8080')
HOST, PORT = WEBUI_ADDR.rsplit(':', 1)
PORT = int(PORT)

STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

NETWORK_FILE = '/etc/twingate/webui-network'
PROFILES_DIR = '/var/lib/twingate/profiles'

MIME_MAP = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
}


def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, IOError):
        return ''


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)


def log(msg):
    ts = datetime.datetime.now().isoformat(timespec='seconds')
    print(f'[{ts}] {msg}', flush=True)

def run_cmd(cmd, input_data=None):
    label = ' '.join(cmd)
    log(f'RUN: {label}')
    if input_data:
        log(f'INPUT: {repr(input_data)}')
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, input=input_data, timeout=120)
        out = r.stdout + r.stderr
        log(f'EXIT: {label} -> rc={r.returncode}')
        if out:
            for line in out.rstrip().splitlines():
                log(f'  {label}: {line}')
        return out, r.returncode
    except subprocess.TimeoutExpired:
        log(f'TIMEOUT: {label}')
        return 'Command timed out', 1
    except Exception as e:
        log(f'ERROR: {label} -> {e}')
        return str(e), 1


def get_status():
    out, rc = run_cmd(['twingate', 'status'])
    return out, rc


def get_resources():
    out, rc = run_cmd(['twingate', 'resources'])
    return out, rc


def generate_clash_rules():
    out, rc = run_cmd(['twingate', 'resources'])
    if rc != 0:
        log('CLASH: resources unavailable, returning empty rules')
        return 'payload: []\n'

    cidr_re = re.compile(r'\b(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\b')
    ip_re = re.compile(r'\b(\d{1,3}(?:\.\d{1,3}){3})\b')
    domain_re = re.compile(r'\b((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})\b')

    rules = []
    seen = set()

    for line in out.splitlines():
        for m in cidr_re.finditer(line):
            val = m.group(1)
            if val not in seen:
                seen.add(val)
                rules.append(f'  - IP-CIDR,{val},no-resolve')

        for m in ip_re.finditer(cidr_re.sub('', line)):
            val = m.group(1)
            if val not in seen:
                seen.add(val)
                rules.append(f'  - IP-CIDR,{val}/32,no-resolve')

        for m in domain_re.finditer(line):
            val = m.group(1).lower()
            if val not in seen and not ip_re.fullmatch(val):
                seen.add(val)
                rules.append(f'  - DOMAIN-SUFFIX,{val}')

    content = 'payload:\n' + '\n'.join(rules) + '\n' if rules else 'payload: []\n'
    log(f'CLASH: generated {len(rules)} rules')
    return content


def detect_relay_ports():
    """Scan /proc/net/tcp for the Twingate data engine's relay sockets
    (ESTABLISHED to a public IP on a high port) and return an inclusive
    (lo, hi) port range covering them, widened to at least 30000-30020."""
    lo, hi, seen = 30000, 30020, []
    try:
        with open('/proc/net/tcp') as f:
            next(f, None)
            for line in f:
                p = line.split()
                if len(p) < 4 or p[3] != '01':  # 01 = ESTABLISHED
                    continue
                iphex, porthex = p[2].split(':')
                port = int(porthex, 16)
                if not 20000 <= port <= 40000:
                    continue
                o = [int(iphex[i:i + 2], 16) for i in (6, 4, 2, 0)]  # little-endian
                if o[0] in (0, 10, 127) or (o[0] == 172 and 16 <= o[1] <= 31) \
                        or (o[0] == 192 and o[1] == 168):
                    continue  # private / loopback
                seen.append(port)
    except (OSError, ValueError):
        pass
    if seen:
        lo, hi = min(lo, min(seen)), max(hi, max(seen))
    log(f'CLASH: relay port range {lo}-{hi} (observed {sorted(set(seen)) or "none"})')
    return lo, hi


def resource_domains():
    """Domain suffixes of the current Twingate resources, for routing them to
    the Twingate proxy. Strips leading '*.' and dedups; skips IPs/twingate.com."""
    out, rc = run_cmd(['twingate', 'resources'])
    if rc != 0:
        return []
    domain_re = re.compile(r'\b((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})\b')
    ip_re = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$')
    seen = set()
    for line in out.splitlines():
        for m in domain_re.finditer(line):
            d = m.group(1).lower().lstrip('*').lstrip('.')
            if d and not ip_re.match(d) and 'twingate.com' not in d:
                seen.add(d)
    # Collapse: keep the broadest suffixes, drop subdomains they already cover
    # (e.g. keep feedme.farm, drop grafana.feedme.farm / argocd.feedme.farm).
    result = []
    for d in sorted(seen, key=lambda x: (x.count('.'), x)):
        if not any(d == k or d.endswith('.' + k) for k in result):
            result.append(d)
    return result


def build_clash_override(host, port, node, region, process, accel_domains=''):
    """Generate a copy-paste Clash Party (mihomo) override: route the Twingate
    resources through this container's HTTP proxy, and accelerate the relay by
    sending the container's Docker egress (on the relay ports) through a chosen
    node group. Requires Clash TUN mode on the client to capture Docker's
    backend. Relay port range and resource domains are auto-detected.

    accel_domains: extra comma-separated domains whose Docker-backend traffic
    should also go through the node (some resources aren't reached over the
    relay ports and need a domain match)."""
    lo, hi = detect_relay_ports()
    domains = resource_domains()
    rule_lines = '\n'.join(f'  - DOMAIN-SUFFIX,{d},Twingate' for d in domains) \
        or '  # (no resources yet — log in first, then regenerate)'
    dom_rules = ''.join(
        f'  - AND,((PROCESS-NAME,{process}),(DOMAIN,{d})),{node}\n'
        for d in (x.strip() for x in accel_domains.split(',')) if d)
    return f"""# Generated by the Twingate Web UI. Paste into your Clash Party / mihomo
# GLOBAL override. REQUIRES Clash TUN mode (Docker's backend makes raw
# connections the system HTTP proxy cannot capture).
proxies+:
  - name: twingate
    type: http
    server: {host}
    port: {port}

proxy-groups+:
  - name: Twingate
    type: select
    proxies:
      - twingate
  - name: {node}
    type: url-test
    include-all: true
    filter: "(?i){region}"
    url: http://www.gstatic.com/generate_204
    interval: 300

+rules:
  # Accelerate the Twingate DATA relay: the local Docker container's relay
  # sockets appear on the host as {process} (TCP, ports {lo}-{hi}); send just
  # those through the {node} group. {process} is the macOS Docker Desktop name.
  - AND,((PROCESS-NAME,{process}),(NETWORK,TCP),(DST-PORT,{lo}-{hi})),{node}
{dom_rules}  # Route the Twingate resources through this container's proxy:
{rule_lines}
"""


def do_login(network):
    log(f'LOGIN: network={network}')
    run_cmd(['twingate', 'stop'])
    clear_profiles()
    write_file(NETWORK_FILE, network)
    setup_input = f'A\n{network}\n{network}\nn\nn\ny\ny\n'
    run_cmd(['twingate', 'setup'], input_data=setup_input)
    run_cmd(['twingate', 'start'])
    log('LOGIN: done')


def clear_profiles():
    log(f'CLEAR: {PROFILES_DIR}')
    try:
        for name in os.listdir(PROFILES_DIR):
            path = os.path.join(PROFILES_DIR, name)
            if os.path.isfile(path) or os.path.islink(path):
                os.remove(path)
                log(f'CLEAR: removed {path}')
    except FileNotFoundError:
        log(f'CLEAR: {PROFILES_DIR} does not exist')
    except Exception as e:
        log(f'CLEAR: failed -> {e}')


class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/status':
            s, rc = get_status()
            self._json({'ok': rc == 0, 'status': s})
            return
        if self.path == '/resources':
            s, rc = get_resources()
            self._json({'ok': rc == 0, 'resources': s})
            return
        if self.path == '/config':
            self._json({'network': read_file(NETWORK_FILE)})
            return
        if self.path == '/rule-twingate.yaml':
            content = generate_clash_rules()
            body = (content or 'payload: []\n').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/yaml; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="rule-twingate.yaml"')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.split('?', 1)[0] == '/clash-override.yaml':
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            def _p(k, default):
                return (q.get(k, [default])[0] or default).strip()
            content = build_clash_override(
                _p('host', '127.0.0.1'), _p('port', '7575'),
                _p('node', 'Singapore'), _p('region', 'singapore|🇸🇬|新加坡'),
                _p('process', 'com.docker.backend'),
                _p('domains', ''))
            body = content.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/yaml; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="clash-override.yaml"')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._serve_static(self.path)

    def do_POST(self):
        if self.path != '/login':
            self._json({'ok': False, 'error': 'not found'}, 404)
            return
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode()
        try:
            params = json.loads(body)
        except json.JSONDecodeError:
            self._json({'ok': False, 'error': 'invalid json'}, 400)
            return
        network = (params.get('network') or '').strip()
        if not network:
            self._json({'ok': False, 'error': 'network is required'}, 400)
            return
        do_login(network)
        self._json({'ok': True})

    def _serve_static(self, path):
        if path == '/':
            path = '/index.html'
        _, ext = os.path.splitext(path)
        mime = MIME_MAP.get(ext, 'application/octet-stream')
        filepath = os.path.join(STATIC_DIR, path.lstrip('/'))
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
        except (OSError, IOError):
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log(f'HTTP: {self.client_address[0]} - {fmt % args}')


if __name__ == '__main__':
    log(f'Server starting on {HOST}:{PORT}')
    server = http.server.HTTPServer((HOST, PORT), Handler)
    log('Server ready')
    server.serve_forever()
