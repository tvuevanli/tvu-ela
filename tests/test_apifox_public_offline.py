#!/usr/bin/env python3
"""apifox public doc and diff, offline: the turbo-stream decode (a number stored at an index is a number, not a
reference), the page payload scan, the host guard, the catalog walk, the shared converter, and the diff's matching
(exact, by unique path suffix, ambiguity left unmatched) and comparison. Synthetic data; no network, no session."""
import json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "apifox"))
import apifox as A  # noqa: E402
import pubdoc as P  # noqa: E402

failures = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


# ── turbo-stream ──────────────────────────────────────────────────────────────
# {"enum": [0, 1], "n": 7, "none": null}: keys and values are indices; 0 and 1 are stored as values at 4 and 5
arr = [{"_1": 2, "_3": 8, "_6": -5}, "enum", [4, 5], "n", 0, 1, "none", "unused", 7]
got = P.resolve(arr)
check("a number stored at an index is literal (enum [0, 1], not the root)", got.get("enum") == [0, 1])
check("a stored 7 resolves to 7", got.get("n") == 7)
check("a negative index is null", "none" in got and got["none"] is None)

page = 'x<script>window.__remixContext.streamController.enqueue("[{\\"_1\\":2},\\"a\\",\\"b \\\\\\"q\\\\\\"\\"]");</script>'
check("the page payload is found and unescaped", P.resolve(P.html_stream(page)) == {"a": 'b "q"'})


def exits(fn, *a):
    try:
        fn(*a)
        return None
    except SystemExit as e:
        return e.code


check("a path that leaves the doc host is refused before any request", exits(P.get, "@evil.example/x", "sid") == P.EX_REMOTE)
check("is_public: the doc URL", P.is_public("https://document.tvunetworks.com/api-1", {}))
check("is_public: a docs: name with this site's apidog id", P.is_public("public", {"public": {"apidog": P.APIDOG_PROJECT}}))
check("is_public: another apidog id is not this site", not P.is_public("public", {"public": {"apidog": "1"}}))
check("is_public: an Apifox project name is not", not P.is_public("ur", {}))

# no session → exit 4 with the login hint, never another account
with tempfile.TemporaryDirectory() as t:
    P.SESSION_FILE = os.path.join(t, "session.json")
    json.dump({"tvu-com": {"sid": "x"}}, open(P.SESSION_FILE, "w"))
    check("only the test-account session is read (the owner's own is ignored)", exits(P.sid) == P.EX_AUTH)
    json.dump({"tvu-com-test": {"cookies": {"SID": "s"}}}, open(P.SESSION_FILE, "w"))
    check("the test account's SID is taken from its cookies", P.sid() == "s")

# ── the catalog and the converter, from a synthetic sidebar and endpoint ──────
with tempfile.TemporaryDirectory() as t:
    P.CACHE = t
    tree = [{"type": "apiDetailFolder", "id": 1, "name": "MediaHub API", "children": [
        {"type": "apiDetailFolder", "id": 2, "name": "route-api", "children": [
            {"type": "apiDetail", "id": 10, "name": "connect", "method": "post", "path": "/mediahub/api/v2/route/connect"}]},
        {"type": "doc", "id": 3, "name": "URLs"}]}]
    def walk_only():   # the catalog as P.catalog() stores it (its walk needs the page; this mirrors its output)
        out = []
        def walk(nodes, trail):
            for x in nodes:
                if x["type"] == "apiDetail":
                    out.append({"kind": "endpoint", "id": str(x["id"]), "name": x["name"], "folder": trail, "method": x["method"], "path": x["path"], "status": ""})
                elif x["type"] == "doc":
                    out.append({"kind": "doc", "id": str(x["id"]), "name": x["name"], "folder": trail})
                else:
                    out.append({"kind": "folder", "id": str(x["id"]), "name": x["name"], "folder": trail}); walk(x["children"], trail + [x["name"]])
        walk(tree, [])
        return out
    P._store("catalog.json", walk_only())
    P._store("api-10.json", {"op": {"id": 10, "name": "connect", "method": "post", "path": "/mediahub/api/v2/route/connect", "operationId": "connect",
                                    "parameters": {"query": [{"name": "projectId", "required": True, "type": "string"}], "header": [{"name": "SID"}]},
                                    "requestBody": {"type": "application/json", "jsonSchema": {"$ref": "#/definitions/77"}, "mediaType": "application/json"},
                                    "responses": [{"code": "200", "contentType": "json", "jsonSchema": {}}]},
                             "defs": {"77": {"name": "ConnectParam", "type": "object", "properties": {"sourceId": {"type": "string"}}, "required": ["sourceId"]}}})
    stub = P.load(A.to_openapi)
    op = stub["paths"]["/mediahub/api/v2/route/connect"]["post"]
    check("catalog-only load: tag is the folder path", op["tags"] == ["MediaHub API/route-api"])
    check("catalog-only load: marked without detail, slug kept", op["x-ela-detail"] is False and op["x-ela-slug"] == "api-10")
    full = P.load(A.to_openapi, hydrate=lambda e: True)
    op = full["paths"]["/mediahub/api/v2/route/connect"]["post"]
    check("hydrated load: parameters and detail", op["x-ela-detail"] and any(p["name"] == "projectId" for p in op["parameters"]))
    check("hydrated load: the body's definition is renamed to its schema name",
          op["requestBody"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ConnectParam"}
          and "ConnectParam" in full["components"]["schemas"])
    check("the catalog keeps docs and folders", {e["kind"] for e in full["x-ela-catalog"]} == {"folder", "doc", "endpoint"})

# ── diff ──────────────────────────────────────────────────────────────────────
def o(**kw):
    return {"summary": kw.pop("summary", ""), "tags": kw.pop("tags", []), **kw}


Aops = [("POST", "/mediahub/api/v2/route/connect", o()), ("GET", "/mediahub/api/v1/schedule/{id}", o()),
        ("GET", "/x/a/list", o()), ("GET", "/y/a/list", o()), ("DELETE", "/only/public", o())]
Bops = [("POST", "/mediahub/api/v2/route/connect", o()), ("GET", "/api/v1/schedule/{scheduleId}", o()),
        ("GET", "/a/list", o()), ("PUT", "/only/internal", o())]
pairs, only_a, only_b = A.match_ops(Aops, Bops)
how = {(x[1], y[1]): h for x, y, h in pairs}
check("exact match", how.get(("/mediahub/api/v2/route/connect", "/mediahub/api/v2/route/connect")) == "exact")
check("suffix match across a gateway prefix, path parameter names ignored",
      how.get(("/mediahub/api/v1/schedule/{id}", "/api/v1/schedule/{scheduleId}")) == "suffix")
check("a suffix two operations claim is not guessed", not any(y[1] == "/a/list" for _, y, _ in pairs) and len(only_a) == 3)
check("the rest is reported on its side", [x[1] for x in only_b] == ["/a/list", "/only/internal"])

d = {"components": {"schemas": {"P": {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}, "required": ["a"]}}}}
oa = {"parameters": [{"name": "id", "in": "query", "required": True, "schema": {"type": "string"}}, {"name": "SID", "in": "header"}],
      "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/P"}}}}}
ob = {"parameters": [{"name": "id", "in": "query", "required": False, "schema": {"type": "integer"}}],
      "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"a": {"type": "string"}, "c": {"type": "string"}},
                                                                       "required": ["a", "c"]}}}}}
lines = A.compare_ops(d, oa, d, ob)
check("required and type differences of a parameter", "param id (query): required A yes, B no" in lines and "param id (query): type A string, B integer" in lines)
check("the SID header is not compared", not any("SID" in x for x in lines))
check("body fields only on one side, through a $ref", "body fields only in A: b" in lines and "body fields only in B: c" in lines)
check("agreeing operations produce nothing", A.compare_ops(d, oa, d, oa) == [])

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
