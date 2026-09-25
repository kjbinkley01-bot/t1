"""Web dashboard: a page on your home Wi-Fi to see and control Clicker from a phone's browser.

Only devices on your local network can connect (private addresses), a PIN is required, and wrong PINs
lock out for a minute after five tries. The page shows what's running (pause, stop), lets you start the
scripts on your allow list, and can show a screenshot.
"""

import http.cookies
import http.server
import ipaddress
import json
import secrets
import socket
import threading
import time
import urllib.parse

MAX_TRIES = 5
LOCK_S = 60


def lan_addresses():
    """This PC's addresses on the local network (best guess first)."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; it just picks the LAN interface
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    return out or ["127.0.0.1"]


def is_local(ip):
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_private or a.is_loopback or a.is_link_local


class Dashboard:
    """The web server. call(command, args) runs on the window thread and returns a dict (or PNG bytes)."""

    def __init__(self, port, pin, call):
        self.port, self.pin, self.call = int(port), str(pin), call
        self.sessions = set()
        self.fails = {}   # ip -> [count, locked_until]
        self.server = None
        self.thread = None

    def start(self):
        dash = self

        class Handler(http.server.BaseHTTPRequestHandler):
            server_version = "Clicker"

            def log_message(self, *a):
                pass

            # -------- helpers
            def _send(self, code, body, ctype="application/json", headers=None):
                data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json"
                                                             else body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _authed(self):
                c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
                return "clicker" in c and c["clicker"].value in dash.sessions

            def _allowed(self):
                if not is_local(self.client_address[0]):
                    self._send(403, {"error": "only devices on your local network"})
                    return False
                return True

            def _body(self):
                n = min(int(self.headers.get("Content-Length") or 0), 10_000)
                raw = self.rfile.read(n).decode("utf-8", "replace")
                if "json" in (self.headers.get("Content-Type") or ""):
                    try:
                        return json.loads(raw or "{}")
                    except ValueError:
                        return {}
                return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

            # -------- routes
            def do_GET(self):
                if not self._allowed():
                    return
                path = urllib.parse.urlparse(self.path).path
                if path == "/":
                    self._send(200, PAGE if self._authed() else LOGIN, "text/html; charset=utf-8")
                elif not self._authed():
                    self._send(401, {"error": "log in"})
                elif path == "/api/status":
                    self._send(200, dash.call("status", {}))
                elif path == "/api/screenshot":
                    png = dash.call("screenshot", {})
                    if isinstance(png, bytes):
                        self._send(200, png, "image/png")
                    else:
                        self._send(500, png)
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                if not self._allowed():
                    return
                path = urllib.parse.urlparse(self.path).path
                ip = self.client_address[0]
                if path == "/login":
                    count, until = dash.fails.get(ip, [0, 0])
                    if until > time.time():
                        self._send(429, LOGIN.replace("<!--msg-->", "Too many tries. Wait a minute."),
                                   "text/html; charset=utf-8")
                        return
                    if secrets.compare_digest(str(self._body().get("pin", "")), dash.pin):
                        dash.fails.pop(ip, None)
                        token = secrets.token_urlsafe(24)
                        dash.sessions.add(token)
                        self._send(303, b"", "text/plain",
                                   {"Location": "/", "Set-Cookie": f"clicker={token}; HttpOnly; SameSite=Strict; Path=/"})
                    else:
                        count += 1
                        dash.fails[ip] = [count, time.time() + LOCK_S if count >= MAX_TRIES else 0]
                        self._send(401, LOGIN.replace("<!--msg-->", "Wrong PIN."), "text/html; charset=utf-8")
                    return
                if not self._authed():
                    self._send(401, {"error": "log in"})
                    return
                if path == "/logout":
                    c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
                    dash.sessions.discard(c["clicker"].value if "clicker" in c else "")
                    self._send(200, {"ok": True})
                elif path in ("/api/start", "/api/stop", "/api/pause"):
                    self._send(200, dash.call(path.rsplit("/", 1)[1], self._body()))
                else:
                    self._send(404, {"error": "not found"})

        self.server = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


STYLE = """
:root{--bg1:#3f67ee;--bg2:#6f55e6;--bg3:#b061c4;--bg4:#ec8a86;--glass:rgba(34,22,88,.42);--line:rgba(255,255,255,.22);
--text:#fff;--muted:rgba(255,255,255,.75);--blue:#0a84ff;--red:#ff453a}
*{box-sizing:border-box}body{margin:0;min-height:100vh;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:var(--text);
background:linear-gradient(135deg,var(--bg1),var(--bg2) 40%,var(--bg3) 72%,var(--bg4));padding:16px}
.card{background:var(--glass);border:1px solid var(--line);border-radius:22px;padding:16px;margin:0 auto 14px;max-width:560px;
backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px)}
h1{font-size:20px;margin:4px auto 14px;max-width:560px}h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;
color:var(--muted);margin:0 0 10px}.muted{color:var(--muted);font-size:14px}
button,.btn{font:600 15px inherit;font-family:inherit;border-radius:20px;border:1px solid var(--line);background:rgba(255,255,255,.14);
color:#fff;padding:10px 16px;min-height:44px;cursor:pointer}.primary{background:var(--blue)}.stop{background:var(--red)}
.row{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid rgba(255,255,255,.1)}.row:first-of-type{border-top:0}
.grow{flex:1;min-width:0}.name{font-weight:700}.line{font-size:13px;color:var(--muted);overflow:hidden;text-overflow:ellipsis}
input{font-size:18px;padding:12px;border-radius:14px;border:1px solid var(--line);background:rgba(0,0,0,.25);color:#fff;width:100%}
img{width:100%;border-radius:14px;margin-top:10px}.ok{color:#8ff0a4}.bad{color:#ffb35c}
"""

LOGIN = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,
initial-scale=1"><title>Clicker</title><style>{STYLE}</style></head><body><h1>Clicker</h1><form class="card" method="post"
action="/login"><h2>Enter your PIN</h2><p class="muted"><!--msg--></p><input name="pin" type="password" inputmode="numeric"
autocomplete="current-password" autofocus><p><button class="primary" type="submit">Open dashboard</button></p></form>
</body></html>"""

PAGE = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,
initial-scale=1"><title>Clicker</title><style>{STYLE}</style></head><body>
<h1>Clicker <span class="muted" id="machine"></span></h1>
<div class="card"><h2>Running now</h2><div id="runs" class="muted">Loading...</div>
<p><button class="stop" onclick="act('stop',{{id:'all'}})">Stop everything</button></p></div>
<div class="card"><h2>Start a script</h2><div id="scripts" class="muted"></div></div>
<div class="card"><h2>Screen</h2><button onclick="shot()">Show the screen</button><div id="shot"></div></div>
<div class="card"><h2>Recent runs</h2><div id="hist" class="muted"></div></div>
<div class="card"><p class="muted" id="msg"></p><button onclick="logout()">Log out</button></div>
<script>
function esc(s){{return String(s).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]))}}
async function api(p,o){{const r=await fetch(p,o);if(r.status==401){{location.reload();throw 0}}return r}}
async function act(cmd,body){{const r=await api('/api/'+cmd,{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify(body)}});const j=await r.json();document.getElementById('msg').textContent=j.msg||'';load()}}
async function load(){{try{{const j=await (await api('/api/status')).json();
document.getElementById('machine').textContent=j.machine?('· '+j.machine):'';
const runs=document.getElementById('runs');runs.innerHTML=j.runs.length?'':'Nothing is running.';
for(const r of j.runs){{runs.insertAdjacentHTML('beforeend',`<div class="row"><div class="grow"><div class="name">${{esc(r.name)}}</div>
<div class="line">${{esc(r.line)}}</div></div><button onclick="act('pause',{{id:'${{r.id}}'}})">${{r.paused?'Resume':'Pause'}}</button>
<button class="stop" onclick="act('stop',{{id:'${{r.id}}'}})">Stop</button></div>`)}}
const sc=document.getElementById('scripts');sc.innerHTML=j.scripts.length?'':
'No scripts allowed yet. In Clicker: Settings, Phone remote control, Scripts your phone may start.';
for(const n of j.scripts){{sc.insertAdjacentHTML('beforeend',`<div class="row"><div class="grow name">${{esc(n)}}</div>
<button class="primary" onclick='act("start",{{name:${{JSON.stringify(n)}}}})'>Start</button></div>`)}}
const h=document.getElementById('hist');h.innerHTML=j.history.length?'':'No runs yet.';
for(const e of j.history){{h.insertAdjacentHTML('beforeend',`<div class="row"><div class="grow"><div class="name">${{esc(e.script)}}</div>
<div class="line">${{esc(e.when)}} · ${{esc(e.time)}}</div></div><span class="${{e.result=='finished'?'ok':'bad'}}">${{esc(e.result)}}</span></div>`)}}
}}catch(e){{}}}}
function shot(){{document.getElementById('shot').innerHTML='<img alt="Screen" src="/api/screenshot?'+Date.now()+'">'}}
async function logout(){{await fetch('/logout',{{method:'POST'}});location.reload()}}
load();setInterval(load,2000);
</script></body></html>"""
