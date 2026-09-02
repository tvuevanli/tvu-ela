#!/usr/bin/env bash
# ela SessionStart hook — read-only. Prints context for the session; never writes anything.
# Output: context/evan.md · latest blueprint decisions + status · which mapped repo/area the cwd is in.
set -u
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SITE="$HOME/.claude/ela/site.json"
CWD="${CLAUDE_PROJECT_DIR:-$PWD}"

cat "$ROOT/context/evan.md" 2>/dev/null

[ -f "$SITE" ] || { echo; echo "ela: site file missing — run /ela:setup"; exit 0; }

python3 - "$SITE" "$CWD" <<'PY' 2>/dev/null || true
import json, os, re, sys
site, cwd = sys.argv[1], sys.argv[2]
try:
    s = json.load(open(site))
except Exception:
    sys.exit(0)
records = s.get("records", "")
bp = os.path.join(records, "blueprint")
print()
print(f"## Knowledge base: {records}")
status = os.path.join(bp, "status.md")
if os.path.isfile(status):
    lines = [l.strip().lstrip("- ") for l in open(status) if l.strip() and not l.startswith("#")]
    print("Status: " + " · ".join(lines[:6]))
dec = os.path.join(bp, "decisions")
if os.path.isdir(dec):
    files = sorted(f for f in os.listdir(dec) if re.match(r"\d{4}-\d{2}-\d{2}-.*\.md$", f))
    if files:
        print("Recent decisions (blueprint/decisions/): " + ", ".join(f[:-3] for f in files[-6:]))

# Which mapped repo or area is the cwd in? Minimal parse of host.yaml: areas (2-space keys) and
# repos (list items). The longest matching path wins, so a repo beats its area.
host = os.path.join(s.get("map", ""), "host.yaml")
if os.path.isfile(host):
    entries, cur, section = [], None, None
    for l in open(host):
        if re.match(r"^\w[\w_-]*:", l):
            section = l.split(":")[0]; cur = None
            continue
        if section == "areas":
            m = re.match(r"^  (\S+):\s*$", l)
            if m:
                cur = {"kind": "area", "name": m.group(1)}; entries.append(cur); continue
            m = re.match(r"^    (path|governance|stack):\s*(.+?)\s*$", l)
            if m and cur: cur[m.group(1)] = m.group(2)
        elif section == "repos":
            m = re.match(r"^- name:\s*(.+?)\s*$", l)
            if m:
                cur = {"kind": "repo", "name": m.group(1)}; entries.append(cur); continue
            m = re.match(r"^  (path|governance|stack|area):\s*(.+?)\s*$", l)
            if m and cur: cur[m.group(1)] = m.group(2)
    best = None
    for e in entries:
        p = e.get("path")
        if p and (cwd == p or cwd.startswith(p.rstrip("/") + "/")):
            if best is None or len(p) > len(best["path"]):
                best = e
    if best:
        gov = best.get("governance", "unknown")
        extra = f", stack {best['stack']}" if best.get("stack") else ""
        where = f"repo '{best['name']}'" + (f" (area {best['area']})" if best.get("area") else "") if best["kind"] == "repo" else f"area '{best['name']}'"
        print(f"cwd {cwd} is in {where} — governance {gov}{extra}. Rules are bound to the location: follow that repo's own files.")
    else:
        print(f"cwd {cwd} is not inside any mapped repo or area (host.yaml). Only ela's own rules apply here.")
PY
exit 0
