"""Single-operator local application. Run with Python 3.10 or newer."""
import http.client
import json
import os
import secrets
import socket
import ssl
import threading
import time
import sys
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import demo
from connector import MAX_BYTES, clean_path, discover, execute, fetch, operations, origin

ROOT = Path(__file__).resolve().parent / "web"
PORT = int(os.getenv("WORKBENCH_PORT","8765"))
SESSIONS = {}
LOCK = threading.RLock()
FIXTURE = None


def retire(sid):
    with LOCK:
        old = SESSIONS.pop(sid,None)
        if old and old.get("sample"):
            with FIXTURE.lock:
                FIXTURE.spaces.pop(old["sample"], None)


def reap():
    while True:
        time.sleep(30)
        with LOCK:
            for sid in list(SESSIONS):
                if time.monotonic()-SESSIONS[sid]["seen"] > 1800:
                    retire(sid)


def connect(req):
    sample_key = None
    if req.get("demo") is True:
        sample_key = demo.allocate(FIXTURE)
        base = f"http://127.0.0.1:{FIXTURE.server_port}"
        headers = {"Authorization":"Bearer "+sample_key}
        req = {}
    else:
        base = str(req.get("address","")).strip().rstrip("/")
        scheme, host, port = origin(base)
        parts = urlsplit(base)
        if parts.query or parts.fragment:
            raise ValueError("Use the Axon application root without a query or fragment.")
        clean_path(parts.path)
        if scheme != "https" and host not in ("127.0.0.1","::1","localhost"):
            raise ValueError("Use HTTPS for a live Axon server. HTTP is available for loopback tests.")
        if os.getenv("AXON_BASE_URL") and base != os.environ["AXON_BASE_URL"].rstrip("/"):
            raise ValueError("The address must match the configured Axon installation.")
        headers = {}
        auth = req.get("auth","access")
        secret = str(req.get("secret","")).strip()
        if auth == "refresh" or auth == "login":
            fields = {"refresh_token":secret} if auth=="refresh" else {"username":req.get("username",""),"password":req.get("secret","")}
            if not all(fields.values()):
                raise ValueError("Complete the Axon sign-in fields.")
            route = "/api/v1/token/refresh" if auth=="refresh" else "/api/login_check"
            status, _, data = fetch(base,base+route,"POST",{"Content-Type":"application/x-www-form-urlencoded"},urlencode(fields).encode())
            if status != 200:
                raise ValueError(f"Axon sign-in returned HTTP {status}. Check the credential and authentication method.")
            try:
                secret = json.loads(data)["token"]
            except (KeyError, ValueError, TypeError):
                raise ValueError("Axon sign-in did not return an access token.") from None
        if secret:
            headers["Authorization"] = "Bearer "+secret
    try:
        docs, source, attempts = discover(base,headers,req.get("imported"),req.get("location"))
        ops, seen = [], set()
        for doc, location in docs:
            for op in operations(doc,base,location):
                identity = (op["method"],op["prefix"],op["path"])
                if identity not in seen:
                    seen.add(identity)
                    op["id"] = str(len(ops))
                    ops.append(op)
        state = {"base":base,"headers":headers,"ops":ops,"sample":sample_key,"seen":time.monotonic(),
                 "public":{"nonce":secrets.token_urlsafe(16),"source":source,"attempts":attempts,"sample":bool(sample_key),
                           "address":"Local sample" if sample_key else base,"version":", ".join(str(d.get("info",{}).get("version","")) for d,_ in docs),
                           "ops":[{k:v for k,v in op.items() if k!="prefix"} for op in ops]}}
        return state
    except Exception:
        if sample_key:
            with FIXTURE.lock:
                FIXTURE.spaces.pop(sample_key,None)
        raise


class UI(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def respond(self, code, data, mime="application/json", cookie=None):
        if mime == "application/json":
            data = json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type",mime)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if cookie is not None:
            self.send_header("Set-Cookie",f"aw_session={cookie}; Path=/; HttpOnly; SameSite=Strict"+("" if cookie else "; Max-Age=0"))
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self):
        host = self.headers.get("Host","")
        if host not in (f"127.0.0.1:{PORT}",f"localhost:{PORT}"):
            return self.respond(403,{"error":"Open the workbench through its local address."})
        cookie = SimpleCookie(self.headers.get("Cookie",""))
        sid = cookie["aw_session"].value if "aw_session" in cookie else ""
        with LOCK:
            state = SESSIONS.get(sid)
            if state and time.monotonic()-state["seen"] > 1800:
                retire(sid)
                state = None
            if state:
                state["seen"] = time.monotonic()
        if self.command == "GET":
            files = {"/":("index.html","text/html; charset=utf-8"),"/app.js":("app.js","text/javascript; charset=utf-8"),
                     "/app.css":("app.css","text/css; charset=utf-8")}
            if self.path in files:
                name,mime = files[self.path]
                return self.respond(200,(ROOT/name).read_bytes(),mime)
            if self.path == "/api/state":
                return self.respond(200,{"state":state["public"] if state else None,"defaultAddress":os.getenv("AXON_BASE_URL","")})
            return self.respond(404,{"error":"Unknown resource"})
        if self.headers.get("Origin") != "http://"+host or self.headers.get_content_type() != "application/json":
            return self.respond(403,{"error":"Request must originate from this workbench."})
        size = int(self.headers.get("Content-Length",0))
        if not 0 < size <= MAX_BYTES * 2:
            return self.respond(413,{"error":"Request is empty or exceeds 24 MiB."})
        req = json.loads(self.rfile.read(size))
        if self.path == "/api/connect":
            new = connect(req)
            key = secrets.token_urlsafe(32)
            with LOCK:
                retire(sid)
                SESSIONS[key] = new
            return self.respond(200,new["public"],cookie=key)
        if not state or req.get("nonce") != state["public"]["nonce"]:
            return self.respond(409,{"error":"The connection changed or expired. Reload the workspace."})
        if self.path == "/api/disconnect":
            retire(sid)
            return self.respond(200,{},cookie="")
        if self.path == "/api/run":
            return self.respond(200,execute(state,req))
        return self.respond(404,{"error":"Unknown operation"})

    def do_GET(self):
        try:
            self.dispatch()
        except ssl.SSLCertVerificationError:
            self.respond(502,{"error":"Axon TLS verification failed. Configure AXON_CA_FILE with the internal CA certificate."})
        except (socket.timeout, TimeoutError):
            self.respond(504,{"error":"Axon timed out. Check the outcome in Axon before retrying a write."})
        except (OSError,http.client.HTTPException):
            self.respond(502,{"error":"Could not reach Axon. Check the address, VPN, DNS and TLS configuration. Verify any pending write before retrying."})
        except (ValueError,TypeError,KeyError,IndexError,AttributeError,RecursionError,LookupError) as e:
            self.respond(400,{"error":str(e)[:400] or "Invalid request or description."})
    do_POST = do_GET


if __name__ == "__main__":
    FIXTURE = demo.start()
    threading.Thread(target=reap,daemon=True).start()
    server = ThreadingHTTPServer((os.getenv("WORKBENCH_BIND","127.0.0.1"),PORT),UI)
    print(f"Axon Workbench is ready at http://127.0.0.1:{PORT}",flush=True)
    if "--open" in sys.argv:
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        FIXTURE.shutdown()
