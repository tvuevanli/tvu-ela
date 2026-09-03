#!/usr/bin/env python3
"""Google Docs / Sheets / Drive — read-only, stdlib only. L1: subcommands, --json, exit codes.

  read  <doc url|id>            a Google Doc as plain text (Docs API documents.get, flattened; tables as rows)
  sheet <sheet url|id> [--gid]  a spreadsheet tab as CSV (Drive export)
  list  [text] [--limit N]      Drive: documents/sheets the account can see, newest first; optional name/full-text filter
  info  <url|id>                Drive metadata: name, type, owner, modified

Credentials: GOOGLE_TOKEN_FILE (env or env file) → a Google OAuth token JSON with refresh_token, client_id,
client_secret, token_uri and read-only scopes (documents.readonly, drive.readonly). The access token is
refreshed in memory; the file is never rewritten. Write scopes are refused.
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
"""
import argparse, json, os, re, signal, sys, urllib.error, urllib.parse, urllib.request

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
ALLOWED = {"https://www.googleapis.com/auth/documents.readonly", "https://www.googleapis.com/auth/drive.readonly",
           "https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"}


def env_value(key, env_file=None):
    v = os.environ.get(key)
    if v:
        return v
    for path in filter(None, [env_file, os.environ.get("ELA_ENV_FILE")]):
        try:
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].rstrip("\n")
        except OSError:
            continue
    return None


class Google:
    def __init__(self, env_file):
        path = env_value("GOOGLE_TOKEN_FILE", env_file)
        if not path or not os.path.isfile(os.path.expanduser(path)):
            print("no GOOGLE_TOKEN_FILE (a read-only OAuth token JSON) — run /ela:setup", file=sys.stderr); sys.exit(EX_AUTH)
        t = json.load(open(os.path.expanduser(path)))
        granted = set(t.get("scopes") or [])
        if not granted <= ALLOWED:
            print(f"token carries scopes outside the read-only allowlist: {sorted(granted - ALLOWED)} — refusing", file=sys.stderr); sys.exit(EX_AUTH)
        self.scopes = granted
        body = urllib.parse.urlencode({"client_id": t["client_id"], "client_secret": t["client_secret"],
                                       "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(t.get("token_uri") or "https://oauth2.googleapis.com/token", data=body), timeout=20) as r:
                self.access = json.loads(r.read())["access_token"]
        except urllib.error.HTTPError as e:
            print(f"google: token refresh failed (HTTP {e.code}) — re-authorise the token", file=sys.stderr); sys.exit(EX_AUTH)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"google: unreachable ({e})", file=sys.stderr); sys.exit(EX_REMOTE)

    def need(self, scope):
        if scope not in self.scopes:
            print(f"the token lacks {scope}", file=sys.stderr); sys.exit(EX_AUTH)

    def get(self, url, raw=False, **params):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.access}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                return data.decode("utf-8", "replace") if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (401, 403):
                print(f"google: HTTP {e.code} — no access to this file with the current token", file=sys.stderr); sys.exit(EX_AUTH)
            print(f"google: HTTP {e.code} on {url.split('?')[0]}", file=sys.stderr); sys.exit(EX_REMOTE)


def file_id(ref):
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", ref) or re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", ref) or re.fullmatch(r"([A-Za-z0-9_-]{20,})", ref.strip())
    if not m:
        print(f"{ref}: not a Google Docs/Sheets/Drive url or id", file=sys.stderr); sys.exit(EX_USAGE)
    return m.group(1)


def gid_of(ref):
    m = re.search(r"[#&?]gid=(\d+)", ref)
    return m.group(1) if m else None


# ── Docs → text ───────────────────────────────────────────────────────────────

def para_text(p):
    out = []
    for el in p.get("elements") or []:
        tr = el.get("textRun")
        if tr:
            out.append(tr.get("content", ""))
        elif el.get("inlineObjectElement"):
            out.append("[image]")
        elif el.get("footnoteReference"):
            out.append(f"[^{el['footnoteReference'].get('footnoteNumber','')}]")
    text = "".join(out).rstrip("\n")
    style = (p.get("paragraphStyle") or {}).get("namedStyleType", "")
    m = re.fullmatch(r"HEADING_(\d)", style)
    if m:
        return "\n" + "#" * int(m.group(1)) + " " + text
    if style == "TITLE":
        return "# " + text
    if p.get("bullet"):
        depth = p["bullet"].get("nestingLevel", 0)
        return "  " * depth + "- " + text
    return text


def body_text(content):
    lines = []
    for el in content or []:
        if "paragraph" in el:
            lines.append(para_text(el["paragraph"]))
        elif "table" in el:
            for row in el["table"].get("tableRows") or []:
                cells = []
                for c in row.get("tableCells") or []:
                    cells.append(" ".join(body_text(c.get("content")).split()))
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
        elif "sectionBreak" in el:
            lines.append("")
        elif "tableOfContents" in el:
            pass
    return "\n".join(lines)


def cmd_read(g, a):
    g.need("https://www.googleapis.com/auth/documents.readonly")
    fid = file_id(a.ref)
    d = g.get(f"https://docs.googleapis.com/v1/documents/{fid}")
    if not d:
        print(f"doc {fid}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
    text = body_text((d.get("body") or {}).get("content"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    meta = {"id": fid, "title": d.get("title"), "url": f"https://docs.google.com/document/d/{fid}/edit", "revision": d.get("revisionId")}
    if a.json:
        print(json.dumps(dict(meta, text=text), ensure_ascii=False)); return
    print(f"# {meta['title']}\n{meta['url']}\n\n{text}")


def cmd_sheet(g, a):
    g.need("https://www.googleapis.com/auth/drive.readonly")
    fid = file_id(a.ref); gid = a.gid or gid_of(a.ref)
    url = f"https://www.googleapis.com/drive/v3/files/{fid}/export?mimeType=text/csv"
    csv = g.get(url, raw=True) if not gid else g.get(f"https://docs.google.com/spreadsheets/d/{fid}/export?format=csv&gid={gid}", raw=True)
    if csv is None:
        print(f"sheet {fid}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
    print(json.dumps({"id": fid, "gid": gid, "csv": csv}, ensure_ascii=False) if a.json else csv)


def cmd_list(g, a):
    g.need("https://www.googleapis.com/auth/drive.readonly")
    q = "(mimeType='application/vnd.google-apps.document' or mimeType='application/vnd.google-apps.spreadsheet') and trashed=false"
    if a.text:
        safe = a.text.replace("'", "\\'")
        q += f" and (name contains '{safe}' or fullText contains '{safe}')"
    d = g.get("https://www.googleapis.com/drive/v3/files", q=q, orderBy="modifiedTime desc", pageSize=a.limit,
              fields="files(id,name,mimeType,modifiedTime,owners(displayName,emailAddress),webViewLink)", supportsAllDrives="true", includeItemsFromAllDrives="true")
    rows = [{"id": f["id"], "name": f["name"], "kind": "sheet" if "spreadsheet" in f["mimeType"] else "doc", "modified": f["modifiedTime"][:10],
             "owner": ((f.get("owners") or [{}])[0]).get("displayName", ""), "url": f.get("webViewLink")} for f in (d or {}).get("files", [])]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    if not rows:
        print("no documents match", file=sys.stderr); sys.exit(EX_NOTFOUND)
    for r in rows:
        print(f"{r['kind']:<5} {r['modified']}  {r['name'][:60]:<60} {r['owner'][:18]:<18} {r['id']}")


def cmd_info(g, a):
    g.need("https://www.googleapis.com/auth/drive.readonly")
    fid = file_id(a.ref)
    f = g.get(f"https://www.googleapis.com/drive/v3/files/{fid}", fields="id,name,mimeType,modifiedTime,createdTime,owners(displayName,emailAddress),lastModifyingUser(displayName),webViewLink,size", supportsAllDrives="true")
    if not f:
        print(f"{fid}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
    print(json.dumps(f, ensure_ascii=False, indent=None if a.json else 1))


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Google Docs/Sheets/Drive, read-only.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("read"); p.add_argument("ref"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("sheet"); p.add_argument("ref"); p.add_argument("--gid"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("list"); p.add_argument("text", nargs="?"); p.add_argument("--limit", type=int, default=30); p.add_argument("--json", action="store_true")
    p = sub.add_parser("info"); p.add_argument("ref"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    g = Google(a.env_file)
    {"read": cmd_read, "sheet": cmd_sheet, "list": cmd_list, "info": cmd_info}[a.cmd](g, a)


if __name__ == "__main__":
    main()
