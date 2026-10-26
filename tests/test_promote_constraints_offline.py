#!/usr/bin/env python3
"""Standing constraints, offline: a temporary elak with blueprint/constraints.yaml, read by promote's loader, pin
check and findings, and by the `constraints` subcommand with the lane read stubbed. Nothing is read from a host."""
import atexit, contextlib, datetime, io, json, os, shutil, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import promote as P  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

today = datetime.date.today()
d = lambda n: (today + datetime.timedelta(days=n)).isoformat()
YAML = f"""constraints:
  - id: held-pin
    says: "The frontend stays at or below 2.2.118 on prod 3."
    ruled: "{d(-5)}"
    until: "{d(14)}"
    lift_when: "QA passes the chain end to end"
    source: "archive/held.md"
    applies: ["promote", "brief"]
    pins:
      - service: mediahub-frontend
        lane: prod-3
        max: "2.2.118"
    checks:
      - lanes: ["prod-3"]
        what: "MediaHub mqtt.publish.topic.templates is empty"
  - id: over-pin
    says: "The backend stays at or below 2.1.40 on prod 3."
    ruled: "{d(-5)}"
    until: "{d(14)}"
    applies: ["promote"]
    pins:
      - service: mediahub-backend
        lane: prod-3
        max: "2.1.40"
  - id: expired-recent
    says: "An old pin."
    until: "{d(-3)}"
    pins:
      - service: mediahub-frontend
        lane: prod-3
        max: "2.2.100"
  - id: expired-long
    says: "An older pin."
    until: "{d(-10)}"
    pins:
      - service: mediahub-frontend
        lane: prod-3
        max: "2.2.90"
"""

elak = tempfile.mkdtemp(prefix="ela-elak-")
atexit.register(shutil.rmtree, elak, True)
os.makedirs(os.path.join(elak, "blueprint"))
open(os.path.join(elak, "blueprint", "constraints.yaml"), "w").write(YAML)
P.R.site = lambda: {"elak": elak}
P.QUIET = True
P.R._MAP = {"version_rules": {}}                 # no patch_only slugs; nothing read from the release map

cons = P.load_constraints()
check("the active constraints are loaded", [c["id"] for c in cons["active"]] == ["held-pin", "over-pin"])
check("one expired 3 days ago is listed", [c["id"] for c in cons["expired"]] == ["expired-recent"] and cons["expired"][0]["days_since_expiry"] == 3)
check("one expired 10 days ago is dropped", all(c["id"] != "expired-long" for c in cons["active"] + cons["expired"]))
check("a missing file is no constraints, not an error",
      P.load_constraints(path=os.path.join(elak, "none.yaml")) == {"path": os.path.join(elak, "none.yaml"), "exists": False, "active": [], "expired": [], "error": None})

pin = {"service": "mediahub-frontend", "max": "2.2.118"}
check("a version at the pin is held", P.pin_state(pin, "2.2.118") == "held")
check("any build of the pinned version is held", P.pin_state(pin, "v2.2.118 build 300") == "held")
check("a lower version is held", P.pin_state(pin, "2.2.117") == "held")
check("a higher version is over", P.pin_state(pin, "2.2.119") == "over")
check("an unparsed version is unknown", P.pin_state(pin, "latest") == "unknown" and P.pin_state(pin, None) == "unknown")

def row(svc, frm, to, fl="daily-wed", tl="prod-3"):
    return {"service": svc, "from_lane": fl, "to_lane": tl, "from": {"version": frm, "parsed": P.parse_version(frm)},
            "to": {"version": to, "parsed": P.parse_version(to)}}
lanes = {"from": "daily-wed", "to": "prod-3", "services": [row("mediahub-frontend", "2.2.118", "2.2.110"), row("mediahub-backend", "2.1.42", "2.1.38")]}
F = P.constraint_findings(cons, lanes)
kinds = [(f["severity"], f["kind"], f.get("constraint")) for f in F]
check("a pin the source version breaks stops the promotion", ("stop", "constraint_pin", "over-pin") in kinds)
check("a pin the source version keeps raises nothing", not any(k[1] == "constraint_pin" and k[2] == "held-pin" for k in kinds))
check("each hand check on the target lane is a high open point", ("high", "constraint_check", "held-pin") in kinds)
check("each constraint touching the lane says when it lifts", ("note", "constraint_lift", "held-pin") in kinds and ("note", "constraint_lift", "over-pin") in kinds)
check("a recently expired constraint on the lane is a note", ("note", "constraint_lift", "expired-recent") in kinds)
other = dict(lanes, to="daily-wed", services=[row("mediahub-frontend", "2.2.130", "2.2.110", "qa-cn3", "daily-wed")])
check("a promotion to another lane is untouched", P.constraint_findings(cons, other) == [])

# the subcommand: pins read on their lane, stubbed
P.read_host = lambda env, host, gaps: [{"service": "mediahub-frontend", "lane": "prod-3", "version": "2.2.118"},
                                       {"service": "mediahub-backend", "lane": "prod-3", "version": "2.1.41"}]
out = io.StringIO()
code = 0
with contextlib.redirect_stdout(out):
    try:
        P.cmd_constraints(types.SimpleNamespace(env_file=None, json=True))
    except SystemExit as e:
        code = e.code
res = json.loads(out.getvalue())
states = {p["service"]: p["state"] for c in res["active"] for p in c["pins"]}
check("constraints reads each pin now: one held, one over", states == {"mediahub-frontend": "held", "mediahub-backend": "over"})
check("constraints exits 3 when a pin is over", code == P.EX_LANE and res["counts"] == {"active": 2, "expired": 1, "over": 1})

print("promote constraints: all offline checks passed" if not failures else f"promote constraints: {len(failures)} check(s) failed")
sys.exit(1 if failures else 0)
