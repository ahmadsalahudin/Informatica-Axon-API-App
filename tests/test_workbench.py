"""Run from the project root with python -m unittest discover -s tests -v."""
import base64
import http.client
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import app
from connector import execute, operations


class Service(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body=b"", media="application/json", extra=None):
        if not isinstance(body,bytes):
            body=json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type",media)
        for k,v in (extra or {}).items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/suite/":
            return self.send(200,b'<link rel="service-desc" href="one.json"><link rel="service-desc" href="two.json">',"text/html")
        if self.path.startswith("/suite/") and self.path.endswith(".json"):
            slug=self.path.split("/")[-1].split(".")[0]
            return self.send(200,{"swagger":"2.0","info":{"version":"1"},"basePath":"/svc","paths":{"/"+slug:{"get":{"summary":slug}}}})
        if self.path == "/svc/one":
            return self.send(200,{"auth":self.headers.get("Authorization")=="Bearer fake-access"})
        if self.path.endswith("/download"):
            return self.send(200,b"\x00\xff\x81","application/octet-stream",{"Content-Disposition":'attachment; filename="example.bin"'})
        if self.path == "/missing/":
            return self.send(200,b"Axon landing page","text/html")
        return self.send(404)

    def do_POST(self):
        body=self.rfile.read(int(self.headers.get("Content-Length","0")))
        if self.path in ("/suite/api/login_check","/suite/api/v1/token/refresh"):
            fields=parse_qs(body.decode())
            if fields in ({"username":["fixture"],"password":["fixture-password"]},{"refresh_token":["fixture-refresh"]}):
                return self.send(200,{"token":"fake-access","refresh_token":"fixture-refresh"})
            return self.send(401)
        self.send(200,{"body":base64.b64encode(body).decode(),"contentType":self.headers["Content-Type"],"path":self.path})


class Workbench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.FIXTURE=app.demo.start()
        cls.ui=ThreadingHTTPServer(("127.0.0.1",0),app.UI)
        cls.upstream=ThreadingHTTPServer(("127.0.0.1",0),Service)
        app.PORT=cls.ui.server_port
        cls.origin=f"http://127.0.0.1:{app.PORT}"
        cls.up=f"http://127.0.0.1:{cls.upstream.server_port}"
        for s in (cls.ui,cls.upstream):
            threading.Thread(target=s.serve_forever,daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for s in (cls.ui,cls.upstream,app.FIXTURE):
            s.shutdown()
            s.server_close()

    def setUp(self):
        self.cookie=""

    def request(self,path,body=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",app.PORT)
        h={"Origin":self.origin,"Content-Type":"application/json","Cookie":self.cookie}
        h.update(headers or {})
        conn.request("POST" if body is not None else "GET",path,None if body is None else json.dumps(body),h)
        resp=conn.getresponse()
        if resp.getheader("Set-Cookie"):
            self.cookie=resp.getheader("Set-Cookie").split(";")[0]
        raw=resp.read()
        data=json.loads(raw) if resp.getheader("Content-Type")=="application/json" else raw
        conn.close()
        return resp.status,data

    def connect(self,request):
        status,value=self.request("/api/connect",request)
        self.assertEqual(status,200,value)
        self.state=value
        return value

    def runop(self,method,path,**params):
        op=next(x for x in self.state["ops"] if x["method"]==method and x["path"]==path)
        return self.request("/api/run",{"id":op["id"],"nonce":self.state["nonce"],**params})

    def test_assets_and_session(self):
        for path in ("/","/app.js","/app.css"):
            self.assertEqual(self.request(path)[0],200)
        s=self.connect({"demo":True})
        self.assertTrue(s["sample"])
        self.assertEqual(s["source"],"Published description")
        self.assertEqual(len(s["ops"]),5)
        self.assertEqual(self.request("/api/state")[1]["state"]["nonce"],s["nonce"])
        self.assertEqual(self.request("/api/disconnect",{"nonce":s["nonce"]})[0],200)
        self.assertIsNone(self.request("/api/state")[1]["state"])

    def test_demo_write_then_search_and_update(self):
        self.connect({"demo":True})
        path="/api/v1/object"
        body={"type":"Glossary","object":{"Name":"رقم الحساب"}}
        args={"body":json.dumps(body),"media":"application/json"}
        self.assertEqual(self.runop("POST",path,**args)[0],400)
        _,result=self.runop("POST",path,confirmed=True,**args)
        self.assertEqual(result["status"],201)
        doc=json.loads(result["body"])
        body["object"]={"id":doc["id"],"Name":"Account identifier"}
        self.assertEqual(self.runop("PUT",path,confirmed=True,media="application/json",body=json.dumps(body))[1]["status"],200)
        _,r=self.runop("POST","/unison/v2/facet/_search",media="application/json",body='{"mainFacet":"Glossary"}',confirmed=True)
        self.assertEqual(json.loads(r["body"])["items"][-1]["Name"],"Account identifier")
        self.connect({"demo":True})
        _,r=self.runop("POST","/unison/v2/facet/_search",media="application/json",body='{"mainFacet":"Glossary"}',confirmed=True)
        self.assertEqual(json.loads(r["body"])["total"],2)

    def test_paging_and_axons_error(self):
        self.connect({"demo":True})
        _,r=self.runop("GET","/api/v1/dqrules",values={"query:offset":"1","query:limit":"1"})
        self.assertEqual(json.loads(r["body"])["items"][0]["id"],"DQ-102")
        _,r=self.runop("GET","/bulkupload/v1/job/{jobId}",values={"path:jobId":"missing"})
        self.assertEqual(r["status"],404)

    def test_linked_descriptions_and_auth(self):
        for auth,secret in (("refresh","fixture-refresh"),("login","fixture-password"),("access","fake-access")):
            s=self.connect({"address":self.up+"/suite","auth":auth,"username":"fixture","secret":secret})
            self.assertEqual([x["path"] for x in s["ops"]],["/one","/two"])
            self.assertNotIn(secret,json.dumps(s))
            self.assertTrue(json.loads(self.runop("GET","/one")[1]["body"])["auth"])
        self.assertEqual(self.request("/api/connect",{"address":self.up+"/suite","auth":"refresh","secret":"invalid"})[0],400)

    def test_reference_and_explicit_url(self):
        s=self.connect({"address":self.up+"/missing"})
        self.assertEqual(s["source"],"Reference catalog")
        self.assertEqual(len(s["ops"]),21)
        self.assertTrue(all("HTTP" in a for a in s["attempts"]))
        s=self.connect({"address":self.up,"location":"/suite/two.json"})
        self.assertEqual(s["ops"][0]["title"],"two")

    def test_import_upload_and_download(self):
        from catalog import reference
        doc=reference()
        doc["paths"]={"/upload":doc["paths"]["/bulkupload/v1/job/file"],"/download":{"get":{"summary":"Download"}}}
        self.connect({"address":self.up,"imported":json.dumps(doc)})
        data=b"example\x00\xff"
        _,r=self.runop("POST","/upload",media="multipart/form-data",confirmed=True,values={"query:targetRef":"A B"},
                       form={"file":{"name":"local.xlsx","data":base64.b64encode(data).decode()}})
        sent=json.loads(r["body"])
        self.assertIn(data,base64.b64decode(sent["body"]))
        self.assertIn('name="file"; filename="local.xlsx"',base64.b64decode(sent["body"]).decode("latin1"))
        self.assertEqual(sent["path"],"/upload?targetRef=A+B")
        _,r=self.runop("GET","/download")
        self.assertTrue(r["binary"]);self.assertEqual(r["filename"],"example.bin")
        self.assertEqual(base64.b64decode(r["body"]),b"\x00\xff\x81")

    def test_origin_and_cross_host_boundary(self):
        self.assertEqual(self.request("/api/connect",{"demo":True},{"Origin":"https://unrelated.invalid"})[0],403)
        self.assertEqual(self.request("/api/state",headers={"Host":"unrelated.invalid"})[0],403)
        self.assertEqual(self.request("/api/connect",{"address":self.up,"location":"https://unrelated.invalid/doc"})[0],400)
        self.connect({"demo":True})
        self.assertEqual(self.request("/api/run",{"id":"0","nonce":"stale"})[0],409)

    def test_nondefault_server_and_local_ref(self):
        doc={"openapi":"3.0.3","components":{"parameters":{"id":{"name":"id","in":"path","required":True,"schema":{"type":"string"}}}},
             "paths":{"/r/{id}":{"parameters":[{"$ref":"#/components/parameters/id"}],"get":{"servers":[{"url":"https://other.invalid"}]}}}}
        ops=operations(doc,self.up,self.up+"/docs/spec.json")
        self.assertTrue(ops[0]["unsupported"])
        self.assertEqual(ops[0]["params"][0]["name"],"id")
        doc["paths"]["/r/{id}"]["get"]["servers"]=[{"url":"./v1"}]
        ops=operations(doc,self.up,self.up+"/docs/spec.json")
        self.assertEqual(ops[0]["prefix"],self.up+"/docs/v1")
        with self.assertRaises(ValueError):
            execute({"ops":ops,"base":self.up,"headers":{}},{"id":"0","values":{"path:id":".."}})
