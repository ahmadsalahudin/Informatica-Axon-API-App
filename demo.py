"""Local HTTP fixture. Each connection gets an isolated set of synthetic records."""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from catalog import reference

RULES = [
    {"id":"DQ-101","name":"Customer identifier completeness","domain":"Customer","status":"Active"},
    {"id":"DQ-102","name":"Account currency validity","domain":"Accounts","status":"Active"},
    {"id":"DQ-103","name":"Branch code consistency","domain":"Reference data","status":"In review"},
    {"id":"DQ-104","name":"Settlement date accuracy","domain":"Payments","status":"Active"}]


def demo_spec():
    doc = reference()
    doc["info"] = {"title":"Axon sample environment","version":"Demo 1.0"}
    for path in list(doc["paths"]):
        if path not in ("/api/v1/dqrules","/api/v1/object","/unison/v2/facet/_search","/bulkupload/v1/job/{jobId}"):
            del doc["paths"][path]
    del doc["paths"]["/api/v1/object"]["delete"]
    for method, example in (("post", {"Name":"Settlement currency"}),("put",{"id":"G-1","Name":"Account holder"})):
        doc["paths"]["/api/v1/object"][method]["requestBody"]["content"]["application/json"]["example"] = {
            "type":"Glossary","stopOnWarning":True,"object":example}
    doc["paths"]["/bulkupload/v1/job/{jobId}"]["get"]["parameters"][0]["schema"]["default"] = "1"
    return doc


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, value, headers=None):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        for k,v in (headers or {}).items():
            self.send_header(k,v)
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self):
        path = urlsplit(self.path)
        token = self.headers.get("Authorization","").removeprefix("Bearer ")
        with self.server.lock:
            records = self.server.spaces.get(token)
            if records is None:
                return self.reply(401,{"error":"Sample session expired"})
            if path.path == "/":
                return self.reply(200,{"service":"Local fixture"},{"Link":'</description.json>; rel="service-desc"'})
            if path.path == "/description.json":
                return self.reply(200,demo_spec())
            if path.path == "/api/v1/dqrules":
                q = parse_qs(path.query)
                offset, limit = (int(q.get(k,[v])[0]) for k,v in (("offset",0),("limit",10)))
                return self.reply(200,{"items":RULES[offset:offset+limit],"total":len(RULES)})
            if path.path.startswith("/bulkupload/v1/job/"):
                return self.reply(200,{"id":1,"status":"Completed","itemsCount":4}) if path.path.endswith("/1") else self.reply(404,{"error":"Unknown job"})
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))) or b"{}")
            if path.path == "/unison/v2/facet/_search":
                rows = [r for r in records if r["type"]==payload.get("mainFacet")]
                properties = payload.get("searchScopes",{}).get("mainFacet",{}).get("properties",{})
                offset, limit = int(properties.get("offset",0)), int(properties.get("limit",20))
                return self.reply(200,{"items":rows[offset:offset+limit],"total":len(rows)})
            if path.path == "/api/v1/object" and self.command in ("POST","PUT"):
                obj = payload.get("object",{})
                if not obj.get("Name") or not payload.get("type"):
                    return self.reply(422,{"error":"Supply type and object.Name"})
                if self.command=="POST":
                    row = {"Name":obj["Name"],"type":payload["type"],"id":"G-"+str(len(records)+1)}
                    records.append(row)
                    return self.reply(201,row)
                for row in records:
                    if row["id"]==obj.get("id"):
                        row["Name"]=obj["Name"]
                        return self.reply(200,row)
                return self.reply(404,{"error":"Unknown object"})
            return self.reply(404,{"error":"Unknown sample operation"})

    def do_GET(self):
        try:
            self.dispatch()
        except (ValueError, KeyError, TypeError, AttributeError):
            self.reply(400,{"error":"Invalid sample request"})

    do_POST = do_PUT = do_GET


def start():
    server = ThreadingHTTPServer(("127.0.0.1",0),Fixture)
    server.lock = threading.Lock()
    server.spaces = {}
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


def allocate(server):
    key = secrets.token_urlsafe(24)
    with server.lock:
        server.spaces[key] = [{"id":"G-1","Name":"Customer account","type":"Glossary"},
                              {"id":"G-2","Name":"Beneficiary bank","type":"Glossary"}]
    return key
