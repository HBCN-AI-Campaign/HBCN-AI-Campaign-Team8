"""Optional evaluation-only SSH tunnel. Reads credentials in memory; pins host key."""
import base64
import hashlib
from pathlib import Path
import re
import select
import socketserver
import threading
import json
import shlex

import httpx


class SshModelClient:
    """Evaluation transport: use the server's working HTTPS egress, no remote files."""
    def __init__(self,tunnel): self.tunnel=tunnel
    def post(self,url,*,headers,json):
        script="""import sys,json,urllib.request,urllib.error
x=json.load(sys.stdin)
try:
 r=urllib.request.urlopen(urllib.request.Request(x['url'],data=json.dumps(x['body']).encode(),headers=x['headers']),timeout=120)
 print(json.dumps({'status':r.status,'body':r.read(4000000).decode()}))
except urllib.error.HTTPError as e:
 print(json.dumps({'status':e.code,'body':e.read(4000000).decode()}))
"""
        try:
            stdin,stdout,stderr=self.tunnel.client.exec_command("python3 -c "+shlex.quote(script),timeout=150)
            stdin.write(__import__('json').dumps(dict(url=url,headers={"Content-Type":"application/json",**headers},body=json)))
            stdin.channel.shutdown_write()
            raw=stdout.read().decode()
            error=stderr.read()
            if error or not raw: raise ValueError("remote transport error")
            data=__import__('json').loads(raw)
            return httpx.Response(data['status'],text=data['body'],request=httpx.Request('POST',url))
        except Exception:
            raise httpx.ConnectError("SSH_MODEL_TRANSPORT_FAILED") from None


class OcrTunnel:
    def __init__(self,resource_file,host_key,remote_port=7888):
        import paramiko
        fields={k.strip():v.strip() for k,v in re.findall(r"(?m)^([^\n:=：]+)[:=：]\s*(.*)$",Path(resource_file).read_text(encoding="utf-8-sig"))}
        class Pinned(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self,client,hostname,key):
                actual="SHA256:"+base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
                if not host_key or actual!=host_key:
                    raise RuntimeError("SSH_HOST_KEY_MISMATCH")
                client.get_host_keys().add(hostname,key.get_name(),key)
        self.client=paramiko.SSHClient()
        self.client.set_missing_host_key_policy(Pinned())
        self.client.connect(fields["公网IP"],port=int(fields.get("SSH端口",22)),username=fields["用户名"],
            password=fields["root初始密码"],look_for_keys=False,allow_agent=False,timeout=15,banner_timeout=15,auth_timeout=15)
        transport=self.client.get_transport();transport.set_keepalive(20)
        class Handler(socketserver.BaseRequestHandler):
            def handle(inner):
                channel=transport.open_channel("direct-tcpip",("127.0.0.1",remote_port),inner.client_address,timeout=15)
                try:
                    while True:
                        ready,_,_=select.select([inner.request,channel],[],[],30)
                        if inner.request in ready:
                            data=inner.request.recv(65536)
                            if not data: break
                            channel.sendall(data)
                        if channel in ready:
                            data=channel.recv(65536)
                            if not data: break
                            inner.request.sendall(data)
                finally:
                    channel.close()
        class Server(socketserver.ThreadingTCPServer):
            daemon_threads=True
            allow_reuse_address=True
        self.server=Server(("127.0.0.1",0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url=f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown();self.server.server_close();self.client.close()

    def __enter__(self): return self
    def __exit__(self,*args): self.close()
