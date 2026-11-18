"""Bounded, same-origin HTTP transport and catalog-driven request construction."""
import base64
import http.client
import json
import mimetypes
import os
import re
import secrets
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import quote, urlencode, urljoin, urlsplit, unquote

from catalog import reference

MAX_BYTES = 12 * 1024 * 1024
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
BLOCK_HEADERS = {"host", "authorization", "cookie", "content-length", "content-type", "connection",
                 "transfer-encoding", "expect", "upgrade", "te", "trailer", "forwarded"}


def origin(url):
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError("Enter an HTTP or HTTPS address without embedded credentials.")
    return parts.scheme, parts.hostname.lower(), parts.port or (443 if parts.scheme == "https" else 80)


def clean_path(path):
    decoded = path
    for _ in range(5):
        new = unquote(decoded)
        if new == decoded:
            break
        decoded = new
    if ("\\" in decoded or decoded.startswith("//") or any(p in (".", "..") for p in decoded.split("/"))
            or any(ord(c) < 32 or ord(c) == 127 for c in decoded)):
        raise ValueError("The address contains an invalid path.")
    return path


def target(base, url):
    if origin(base) != origin(url):
        raise ValueError("The description points to a different server. Use a same-origin description.")
    clean_path(urlsplit(url).path)
    return url


def fetch(base, url, method="GET", headers=None, body=None, timeout=20):
    target(base, url)
    parts = urlsplit(url)
    if parts.scheme == "https":
        context = ssl.create_default_context()
        if os.getenv("AXON_CA_FILE"):
            context.load_verify_locations(os.environ["AXON_CA_FILE"])
        conn = http.client.HTTPSConnection(parts.hostname, parts.port, timeout=timeout, context=context)
    else:
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)
    try:
        path = parts.path or "/"
        conn.request(method, path + ("?" + parts.query if parts.query else ""), body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Response exceeded 12 MiB. For a write, check its outcome in Axon before retrying.")
        return response.status, response.headers, data
    finally:
        conn.close()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        href = a.get("href") or ""
        if tag in ("a", "link") and ("service-desc" in (a.get("rel") or "").split()
                or re.search(r"(?:openapi|swagger)[^/]*\.json(?:$|\?)", href, re.I)):
            self.urls.append(href)


def as_spec(data):
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeError):
        return None
    if isinstance(doc, dict) and (str(doc.get("openapi", "")).startswith("3.") or doc.get("swagger") == "2.0") and isinstance(doc.get("paths"), dict):
        return doc
    return None


def discover(base, headers, imported=None, location=None):
    if imported is not None:
        doc = as_spec(imported)
        if doc is None:
            raise ValueError("Choose a bundled OpenAPI 3 or Swagger 2 JSON file with a paths object.")
        return [(doc,base + "/")], "Imported JSON", []
    if location:
        url = target(base, urljoin(base + "/", location))
        status, _, data = fetch(base, url, headers=headers)
        doc = as_spec(data)
        if status != 200 or doc is None:
            raise ValueError(f"Description URL returned HTTP {status}. Supply the JSON document URL.")
        return [(doc,url)], "Published description", [f"Description · HTTP {status}"]
    attempts, found = [], []
    candidates = [(base + "/", True)]
    seen = set()
    conventional = [urljoin(base+"/", name) for name in ("openapi.json","swagger.json","v3/api-docs")]
    while len(seen) < 12:
        if not candidates:
            if found or not conventional:
                break
            candidates.append((conventional.pop(0),False))
        url, landing = candidates.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            status, meta, data = fetch(base, url, headers=headers, timeout=6)
        except (OSError, http.client.HTTPException):
            if len(seen) == 1:
                raise
            attempts.append(f"{urlsplit(url).path} · unavailable")
            continue
        attempts.append(f"{urlsplit(url).path} · HTTP {status}")
        doc = as_spec(data)
        if status == 200 and doc is not None:
            found.append((doc,url))
            continue
        links = []
        if status in (301,302,303,307,308) and meta.get("Location"):
            links.append((meta["Location"],landing))
        if landing:
            html = Links()
            html.feed(data[:160000].decode("utf8","replace"))
            links.extend((href,False) for href in html.urls)
            links.extend((href,False) for href, params in re.findall(r"<([^>]+)>([^,]*)",meta.get("Link","")) if "service-desc" in params)
        for href, is_landing in links[:8]:
            candidate = urljoin(url,href)
            try:
                target(base,candidate)
            except ValueError:
                continue
            candidates.append((candidate,is_landing))
    if found:
        return found, "Published description", attempts
    return [(reference(),base+"/")], "Reference catalog", attempts


def deref(doc, item):
    seen = set()
    while isinstance(item, dict) and "$ref" in item:
        ref = item["$ref"]
        if not ref.startswith("#/") or ref in seen:
            raise ValueError("Bundle external references into one JSON file before importing.")
        seen.add(ref)
        item = doc
        for key in ref[2:].split("/"):
            item = item[key.replace("~1", "/").replace("~0", "~")]
    return item


def sample(doc, schema, depth=0):
    if depth > 4:
        return None
    s = deref(doc, schema)
    for key in ("example", "default"):
        if key in s:
            return s[key]
    if s.get("enum"):
        return s["enum"][0]
    if s.get("properties") or s.get("type") == "object":
        return {k: sample(doc, v, depth+1) for k, v in list(s.get("properties", {}).items())[:40]}
    if s.get("type") == "array":
        return [sample(doc, s.get("items", {}), depth+1)]
    return {"integer": 0, "number": 0, "boolean": False}.get(s.get("type"), "")


def operations(doc, base, doc_url):
    result = []
    for path, raw in doc["paths"].items():
        raw = deref(doc, raw)
        for method, op in raw.items():
            if method not in METHODS:
                continue
            unsupported = []
            servers = op.get("servers") or raw.get("servers") or doc.get("servers")
            prefix = base
            if servers:
                server = servers[0]
                address = server["url"]
                for key, v in server.get("variables", {}).items():
                    address = address.replace("{"+key+"}", str(v.get("default", "")))
                prefix = urljoin(doc_url, address).rstrip("/")
            elif "basePath" in doc:
                prefix = urljoin(base+"/", doc["basePath"]).rstrip("/")
            if not path.startswith("/") or "?" in path or "#" in path:
                unsupported.append("Invalid path template")
            try:
                target(base, prefix + path)
            except ValueError as e:
                unsupported.append(str(e))
            params, media = {}, {}
            consumes = op.get("consumes", doc.get("consumes", ["application/json"]))
            body = deref(doc, op.get("requestBody", {}))
            required_body = body.get("required", False)
            formprops, needs = {}, []
            for p in raw.get("parameters", []) + op.get("parameters", []):
                p = deref(doc, p)
                loc, name = p["in"], p["name"]
                s = deref(doc, p.get("schema", p))
                if loc == "body":
                    required_body = p.get("required", False)
                    for c in consumes:
                        media[c] = {"schema": s}
                elif loc == "formData":
                    formprops[name] = {"type": "string", "format": "binary"} if s.get("type") == "file" else s
                    if p.get("required"):
                        needs.append(name)
                elif loc in ("path", "query", "header"):
                    if loc == "header" and (name.lower() in BLOCK_HEADERS or name.lower().startswith(("proxy-", "x-forwarded-"))):
                        if p.get("required") and name.lower() not in ("authorization","content-type"):
                            unsupported.append("Restricted header: " + name)
                        continue
                    if p.get("style") not in (None, "form", "simple", "spaceDelimited", "pipeDelimited") or s.get("type") == "object":
                        unsupported.append("Unsupported parameter serialization: " + name)
                    params[(loc,name)] = {"name": name, "in": loc, "required": p.get("required", False) or loc=="path",
                        "type": s.get("type", "string"), "default": s.get("default", p.get("example", "")), "enum": s.get("enum", []),
                        "collection": p.get("collectionFormat") or {"spaceDelimited":"ssv","pipeDelimited":"pipes"}.get(p.get("style")) or
                        ("multi" if loc=="query" and "openapi" in doc and p.get("explode",True) else "csv")}
                else:
                    unsupported.append("Unsupported parameter location: " + loc)
            if formprops:
                for c in op.get("consumes", doc.get("consumes", ["multipart/form-data"])):
                    media[c] = {"schema":{"properties":formprops,"required":needs}}
            media.update(body.get("content", {}))
            formats = {}
            for c, m in media.items():
                s = deref(doc, m.get("schema", {}))
                ex = m["example"] if "example" in m else sample(doc, s)
                fields = []
                for key, v in s.get("properties",{}).items():
                    v = deref(doc, v)
                    fields.append({"name":key,"file":v.get("format")=="binary","required":key in s.get("required",[]),
                                   "default":v.get("default","")})
                formats[c] = {"example":ex,"fields":fields}
            result.append({"id":str(len(result)), "method":method.upper(),"path":path,"prefix":prefix,
                           "title":op.get("summary") or op.get("operationId") or path,
                           "group":(op.get("tags") or ["General"])[0],"description":op.get("description",""),
                           "params":list(params.values()),"formats":formats,"requiredBody":required_body,
                           "unsupported":unsupported})
    if not result:
        raise ValueError("The description contains no supported HTTP operations.")
    return result


def form_body(fields, values, media):
    parts, pairs = [], []
    boundary = "axon-" + secrets.token_hex(16)
    for f in fields:
        k = f["name"]
        value = values.get(k)
        if value is None or value == "":
            if f["required"]:
                raise ValueError("Supply " + k)
            continue
        name = quote(k, safe="[]_-")
        disp = f'Content-Disposition: form-data; name="{name}"'
        if f["file"]:
            filename = quote(os.path.basename(value["name"]), safe="._-")
            disp += f'; filename="{filename}"\r\nContent-Type: application/octet-stream'
            data = base64.b64decode(value["data"], validate=True)
        else:
            pairs.append((k, str(value)))
            data = str(value).encode()
        parts.append(f"--{boundary}\r\n{disp}\r\n\r\n".encode()+data+b"\r\n")
    if media == "application/x-www-form-urlencoded":
        return urlencode(pairs).encode(), media
    return b"".join(parts)+f"--{boundary}--\r\n".encode(), media+"; boundary="+boundary


def execute(connection, request):
    op = connection["ops"][int(request["id"])]
    if op["id"] != str(request["id"]) or op["unsupported"]:
        raise ValueError("This operation cannot run with this description.")
    if op["method"] not in ("GET","HEAD","OPTIONS") and request.get("confirmed") is not True:
        raise ValueError("Review and confirm this request first.")
    path = op["path"]
    headers = dict(connection["headers"])
    query = []
    for p in op["params"]:
        name, loc = p["name"], p["in"]
        val = request.get("values",{}).get(loc+":"+name, "")
        if val == "":
            if p["required"]:
                raise ValueError("Supply " + name)
            continue
        if p["type"] == "array":
            parsed = json.loads(val)
            if not isinstance(parsed,list):
                raise ValueError("Enter a JSON array for " + name)
            vals = [str(v) for v in parsed]
        else:
            vals = [str(val)]
        if loc == "query" and p["collection"] == "multi":
            query.extend((name,v) for v in vals)
        else:
            v = {"ssv":" ","pipes":"|","tsv":"\t"}.get(p["collection"],",").join(vals)
            if loc == "path":
                if "/" in v or "%" in v or v in ("", ".", ".."):
                    raise ValueError("Use a single path segment for " + name)
                path = path.replace("{"+name+"}",quote(v,safe=""))
            elif loc == "header":
                headers[name] = v
            else:
                query.append((name,v))
    if "{" in path or "}" in path:
        raise ValueError("The description is missing a path parameter.")
    url = op["prefix"]+path+("?" + urlencode(query) if query else "")
    body = None
    media = request.get("media")
    if media:
        if media not in op["formats"]:
            raise ValueError("Select an advertised request format.")
        if media in ("multipart/form-data","application/x-www-form-urlencoded"):
            body, ct = form_body(op["formats"][media]["fields"], request.get("form",{}), media)
        elif media == "application/octet-stream":
            body, ct = base64.b64decode(request["binary"],validate=True), media
        else:
            raw = request.get("body","")
            if raw and "json" in media:
                json.loads(raw)
            body, ct = raw.encode() if raw else None, media
        headers["Content-Type"] = ct
    if op["requiredBody"] and body is None:
        raise ValueError("A request body is required.")
    start = time.monotonic()
    status, meta, data = fetch(connection["base"], url, op["method"], headers, body)
    ct = meta.get_content_type()
    binary = bool(data) and not (ct.startswith("text/") or any(t in ct for t in ("json","xml","javascript")))
    filename = meta.get_filename() or ("response" + (mimetypes.guess_extension(ct) or ".bin"))
    return {"status":status,"type":ct,"bytes":len(data),"ms":round((time.monotonic()-start)*1000),
            "binary":binary,"filename":filename,"body":base64.b64encode(data).decode() if binary else data.decode(meta.get_content_charset() or "utf8","replace")}
