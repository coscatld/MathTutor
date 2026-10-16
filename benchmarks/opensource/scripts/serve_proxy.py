"""Loopback-only experiment transport. Vendor key stays in process memory."""
import argparse,asyncio,hashlib,json,os,secrets,signal,ssl,threading,time,sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx
from mathtutor.infrastructure.keychain_secret_store import KeychainSecretStore
p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--log',required=True);p.add_argument('--stdin-key',action='store_true');a=p.parse_args()
vendor_key=sys.stdin.readline().strip() if a.stdin_key else asyncio.run(KeychainSecretStore().get('generative.api_key.deepseek'))
if not vendor_key:raise SystemExit('Configured DeepSeek credential unavailable')
token=secrets.token_urlsafe(32);lock=threading.Lock();log=Path(a.log);log.parent.mkdir(parents=True,exist_ok=True)
client=httpx.Client(timeout=180,verify=ssl.create_default_context(cafile='/etc/ssl/cert.pem'),trust_env=False,limits=httpx.Limits(max_connections=40,max_keepalive_connections=20))
def record(r):
    with lock:
        with log.open('a') as f:f.write(json.dumps({'time':time.time(),**r})+'\n')
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):self.relay()
    def do_POST(self):self.relay()
    def relay(self):
        if self.headers.get('Authorization')!='Bearer '+token:self.send_error(401);return
        route=self.path.removeprefix('/v1')
        if (self.command,route) not in [('GET','/models'),('POST','/chat/completions')]:self.send_error(404);return
        start=time.monotonic();n=int(self.headers.get('Content-Length','0'))
        if n>2_000_000:self.send_error(413);return
        body=self.rfile.read(n);meta={'route':route,'request_sha256':hashlib.sha256(body).hexdigest()}
        try:
            with client.stream(self.command,'https://api.deepseek.com'+route,headers={'Authorization':'Bearer '+vendor_key,'Content-Type':'application/json'},content=body or None) as upstream:
                self.send_response(upstream.status_code);self.send_header('Content-Type',upstream.headers.get('content-type','application/json'));self.end_headers()
                parts=[];size=0
                for part in upstream.iter_bytes():
                    self.wfile.write(part);self.wfile.flush()
                    if size<4_000_000:parts.append(part);size+=len(part)
                payload=b''.join(parts);data={}
                try:data=json.loads(payload)
                except ValueError:
                    for line in payload.decode(errors='replace').splitlines():
                        if line.startswith('data: '):
                            try:
                                v=json.loads(line[6:])
                                if v.get('usage'):data=v
                            except ValueError:pass
                record({**meta,'status':upstream.status_code,'duration_s':time.monotonic()-start,'model':data.get('model'),
                    'usage':data.get('usage'),'finish_reason':next(iter(data.get('choices') or [{}])).get('finish_reason')})
        except Exception as e:
            record({**meta,'status':502,'duration_s':time.monotonic()-start,'error_type':type(e).__name__})
            try:
                self.send_response(502);self.end_headers();self.wfile.write(b'{"error":{"message":"experiment transport unavailable"}}')
            except OSError:pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
config=Path(a.config);config.write_text(json.dumps({'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':token,'model':'deepseek-flash'}));config.chmod(0o600)
def shutdown(*_):threading.Thread(target=server.shutdown,daemon=True).start()
signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
print(json.dumps({'ready':True,'connection_file':str(config),'vendor_key_persisted':False}),flush=True)
try:server.serve_forever()
finally:
    server.server_close();client.close();vendor_key=None;token=None;config.unlink(missing_ok=True)
    record({'event':'credential_reference_cleared_and_proxy_closed'})
