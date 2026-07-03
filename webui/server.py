#!/usr/bin/env python3
import datetime
import http.server
import json
import os
import re
import subprocess
import sys

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
