#!/usr/bin/env python3
"""Servidor local para Sims Cuba: web + multijugador offline por Wi-Fi."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path
from threading import RLock
import json, socket, time, os, sys

ROOT = Path(__file__).resolve().parent
HOST = '0.0.0.0'
PORT = int(os.environ.get('SIMSCUBA_PORT', '8000'))
MAX_CLIENTS = 16
CLIENT_TIMEOUT = 75
LOCK = RLock()
ROOM = {'active': False, 'clients': {}, 'host_events': [], 'next_id': 1, 'last': time.time()}

def local_ips():
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith('127.') and ip not in found:
                found.append(ip)
    except OSError:
        pass
    # Método adicional, útil en Android/Termux y equipos con hostname sin IP LAN.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith('127.') and ip not in found:
            found.insert(0, ip)
    except OSError:
        pass
    return found

def clean_stale():
    now = time.time()
    stale = [cid for cid, c in ROOM['clients'].items() if now - c['last'] > CLIENT_TIMEOUT]
    for cid in stale:
        ROOM['clients'].pop(cid, None)
        ROOM['host_events'].append({'k': 'close', 'cid': cid})
    ROOM['host_events'] = ROOM['host_events'][-500:]

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        # Registro corto y legible en Termux.
        sys.stdout.write('[Sims Cuba] ' + (fmt % args) + '\n')

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body_json(self):
        try:
            n = min(int(self.headers.get('Content-Length', '0')), 2_000_000)
            raw = self.rfile.read(n) if n else b'{}'
            return json.loads(raw.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/health':
            with LOCK:
                clean_stale()
                self.send_json({'ok': True, 'room': ROOM['active'], 'players': len(ROOM['clients']), 'port': PORT})
            return
        if u.path == '/r/poll':
            q = parse_qs(u.query)
            with LOCK:
                clean_stale()
                ROOM['last'] = time.time()
                if q.get('h') == ['1']:
                    events = ROOM['host_events']
                    ROOM['host_events'] = []
                    self.send_json({'ev': events})
                else:
                    cid = str((q.get('c') or [''])[0])
                    c = ROOM['clients'].get(cid)
                    if not c:
                        self.send_json({'ev': [{'close': 1}]})
                    else:
                        c['last'] = time.time()
                        events = c['events']
                        c['events'] = []
                        self.send_json({'ev': events})
            return
        # Página principal y recursos del juego.
        if u.path == '/':
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        data = self.body_json()
        with LOCK:
            clean_stale()
            ROOM['last'] = time.time()
            if u.path == '/r/host':
                for c in ROOM['clients'].values():
                    c['events'].append({'close': 1})
                ROOM.update(active=True, clients={}, host_events=[], next_id=1)
                self.send_json({'ok': True, 'ips': local_ips(), 'port': PORT})
                return
            if u.path == '/r/join':
                if not ROOM['active']:
                    self.send_json({'cid': None, 'error': 'no_room'}, 409); return
                if len(ROOM['clients']) >= MAX_CLIENTS:
                    self.send_json({'cid': None, 'error': 'full'}, 409); return
                cid = str(ROOM['next_id']); ROOM['next_id'] += 1
                name = str(data.get('name') or 'Jugador')[:20]
                ROOM['clients'][cid] = {'events': [], 'last': time.time(), 'name': name}
                ROOM['host_events'].append({'k': 'open', 'cid': cid, 'name': name})
                self.send_json({'cid': cid})
                return
            if u.path == '/r/h':
                # Mensajes enviados por el anfitrión a jugadores concretos.
                for item in data.get('b', [])[:500]:
                    cid = str(item.get('cid', ''))
                    c = ROOM['clients'].get(cid)
                    if c and 'm' in item:
                        c['events'].append({'m': item['m']})
                        c['last'] = time.time()
                        c['events'] = c['events'][-500:]
                self.send_json({'ok': True}); return
            if u.path == '/r/g':
                cid = str(data.get('cid', ''))
                c = ROOM['clients'].get(cid)
                if c:
                    c['last'] = time.time()
                    if data.get('close'):
                        ROOM['clients'].pop(cid, None)
                        ROOM['host_events'].append({'k': 'close', 'cid': cid})
                    elif 'm' in data:
                        ROOM['host_events'].append({'k': 'msg', 'cid': cid, 'm': data['m']})
                self.send_json({'ok': True}); return
            if u.path == '/r/close':
                for c in ROOM['clients'].values():
                    c['events'].append({'close': 1})
                ROOM['active'] = False
                ROOM['clients'] = {}
                ROOM['host_events'] = []
                self.send_json({'ok': True}); return
        self.send_json({'error': 'not_found'}, 404)

if __name__ == '__main__':
    os.chdir(ROOT)
    print('\n=== SIMS CUBA | SERVIDOR LOCAL ===')
    print('Carpeta:', ROOT)
    print('Abre en este dispositivo: http://127.0.0.1:%d' % PORT)
    ips = local_ips()
    if ips:
        print('En otros dispositivos (misma Wi-Fi/hotspot):')
        for ip in ips:
            print('  http://%s:%d' % (ip, PORT))
    else:
        print('No pude detectar la IP Wi-Fi. Comprueba que el Wi-Fi esté conectado.')
    print('Servidor listo. No cierres Termux mientras juegas. Ctrl+C para detener.\n')
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except OSError as e:
        print('No se pudo abrir el puerto %d: %s' % (PORT, e))
        print('Cierra otro servidor que esté usando ese puerto o ejecuta: SIMSCUBA_PORT=8001 python server.py')
