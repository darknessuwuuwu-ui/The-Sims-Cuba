#!/usr/bin/env python3
"""Servidor LAN sencillo para The Sims Cuba. Ejecutar: python3 servidor.py"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, socket, threading, itertools

lock=threading.RLock(); room={'host':False,'clients':{},'events':[]}; ids=itertools.count(1)
def local_ips():
    out=[]
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); out.append(s.getsockname()[0]); s.close()
    except Exception: pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET):
            ip=info[4][0]
            if not ip.startswith('127.') and ip not in out: out.append(ip)
    except Exception: pass
    return out or ['127.0.0.1']
class H(SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
    def sendj(self,obj):
        b=json.dumps(obj).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self): self.send_response(204); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Headers','Content-Type'); self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS'); self.end_headers()
    def body(self):
        n=int(self.headers.get('Content-Length',0)); return json.loads(self.rfile.read(n) or b'{}')
    def do_POST(self):
        path=urlparse(self.path).path
        try: d=self.body()
        except Exception: d={}
        with lock:
            if path=='/r/host':
                room['host']=True; room['clients']={}; room['events']=[]; self.sendj({'ok':1,'ips':local_ips(),'port':8000}); return
            if path=='/r/join':
                if not room['host'] or len(room['clients'])>=8: self.sendj({'cid':None}); return
                cid=str(next(ids)); room['clients'][cid]=[]; room['events'].append({'k':'open','cid':cid,'name':str(d.get('name','Jugador'))[:14]}); self.sendj({'cid':cid}); return
            if path=='/r/h':
                for x in d.get('b',[]):
                    cid=str(x.get('cid',''))
                    if x.get('close'):
                        room['clients'].pop(cid,None); room['events'].append({'k':'close','cid':cid})
                    elif cid in room['clients']: room['clients'][cid].append({'m':x.get('m')})
                self.sendj({'ok':1}); return
            if path=='/r/g':
                cid=str(d.get('cid',''))
                if d.get('close'):
                    if cid in room['clients']: room['clients'].pop(cid,None); room['events'].append({'k':'close','cid':cid})
                elif cid in room['clients']: room['events'].append({'k':'msg','cid':cid,'m':d.get('m')})
                self.sendj({'ok':1}); return
            if path=='/r/close':
                room['host']=False; room['clients'].clear(); room['events']=[]; self.sendj({'ok':1}); return
        self.sendj({'error':'not found'})
    def do_GET(self):
        u=urlparse(self.path); q=parse_qs(u.query)
        if u.path=='/r/poll':
            with lock:
                if q.get('h')==['1']:
                    ev=room['events']; room['events']=[]; self.sendj({'ev':ev}); return
                cid=(q.get('c') or [''])[0]; cl=room['clients'].get(cid)
                if cl is None: self.sendj({'ev':[{'close':1}]}); return
                ev=cl[:]; cl.clear(); self.sendj({'ev':ev}); return
        return super().do_GET()
print('The Sims Cuba LAN: http://127.0.0.1:8000')
print('IP local:', ', '.join(local_ips()))
print('Mantén esta ventana abierta durante la partida.')
ThreadingHTTPServer(('0.0.0.0',8000),H).serve_forever()
