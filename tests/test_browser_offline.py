#!/usr/bin/env python3
"""The browser sense offline: the version panel parsed into services and lanes, the unproven shape recognised."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "browser"))
import browser as B  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

B.lane_suffixes = lambda: {"Prod3": "prod-3", "Prod8": "prod-8", "Test2": "daily-test2"}
PANEL = """TVU MediaHub (ENV: MediaHubProd3)
Frontend: v2.2.111 build162 2026-09-22 10:06:35
Backend:  v2.1.26 build256  2026-09-22 10:06:15
Unified Media Service (ENV: UnifiedMediaProd3)
Frontend: v3.0.30 build185 2026-09-21 10:20:15
Backend:  v1.0.278 build82 2026-08-24 03:08:02
Unified Resources Caller (ENV: URCallerProd3)
Backend:  v2.1.68 build346 2026-09-28 05:46:49
Unified Resources Portal Service (ENV: UR4Prod3)
Backend: { "portal": "1.9.0+89" }
Unified Resources License Service (ENV: UR4Prod3)
Backend: { "volumelicense": "1.9.0+19" }
Home (ENV: Production3) · Billing (ENV: billingp1)"""
r = B.parse_panel(PANEL)
by = {s["slug"]: s for sec in r["sections"] for s in sec["services"]}
check("the panel is proven when ENV lines exist", r["proven"])
check("every ENV maps to its lane", r["lanes"].get("prod-3") == 5)
check("MediaHub frontend and backend read", by["mediahub-frontend"]["version"] == "v2.2.111 build162" and by["mediahub-backend"]["version"] == "v2.1.26 build256")
check("the frontend build parses to M.m.p+BUILD", B.R.vlabel(by["mediahub-frontend"]["parsed"]) == "2.2.111+162")
check("unified media and the caller read", by["unified-media-frontend"]["version"].startswith("v3.0.30") and by["unified-streaming"]["version"].startswith("v2.1.68"))
check("portal and license read from the json backend line", by["ur-portal"]["version"] == "1.9.0+89" and by["volume-license"]["version"] == "1.9.0+19")
check("Home and Billing are recorded with no service row", any(s["title"] == "Billing" for s in r["sections"]) and not any(s["title"] == "Home" and s["services"] for s in r["sections"]))

UNPROVEN = "TVU MediaHub\nFrontend\nBackend\nUnified Media Service\nUnified Resources Caller"
u = B.parse_panel(UNPROVEN)
check("a panel with names only is unproven", not u["proven"] and not u["lanes"])

check("the fix on the panel's lane passes the gate", B.fix_verdict("prod-3", ["daily-test2", "prod-3"]) is None)
check("a fix on QA lanes only names them and stops", "QA lanes only" in (B.fix_verdict("prod-3", ["qa-aws3"]) or ""))
check("a fix on another daily or prod lane says which and asks for the bundle switch", "daily-test2" in (B.fix_verdict("prod-3", ["daily-test2"]) or "") and "login tvu" in B.fix_verdict("prod-3", ["daily-test2"]))
check("no carrying lane is a gate failure, not a pass", B.fix_verdict("prod-3", []) is not None)

print("browser: all offline checks passed" if not failures else f"browser: {len(failures)} check(s) failed")
sys.exit(1 if failures else 0)
