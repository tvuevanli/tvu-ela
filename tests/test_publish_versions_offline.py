#!/usr/bin/env python3
"""`publish.publish_versions` carries the newest desk versions file into <published>/lanes/ and keeps one dated copy,
so a host with no desk (the remote Helm) reads the QA lanes from it. Runs in a temporary directory; no site is read."""
import json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "publish"))
import publish  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


with tempfile.TemporaryDirectory() as t:
    runner, dst = os.path.join(t, "runtime", "runner"), os.path.join(t, "published", "lanes")
    site = {"runtime": os.path.join(t, "runtime")}
    check(publish.publish_versions(site, dst).startswith("not published"), "no runner directory: said, nothing written")
    os.makedirs(runner)
    os.makedirs(dst)
    open(os.path.join(dst, "versions-2026-11-17.json"), "w").write("{}")
    row = {"service": "mediahub-backend", "lane": "qa-cn3", "version": "v2.1.47", "host": "mail", "state": "built"}
    for d in ("2026-11-18", "2026-11-19"):
        json.dump({"date": d, "rows": [row]}, open(os.path.join(runner, f"versions-{d}.json"), "w"))
    open(os.path.join(runner, "2026-11-19-versions-0930.json"), "w").write("{}")   # an intraday read is not the file
    out = publish.publish_versions(site, dst)
    check(out == "published versions-2026-11-19.json", "the newest dated file is published")
    check(sorted(f for f in os.listdir(dst) if "versions" in f) == ["versions-2026-11-19.json"],
          "one dated copy is kept, the older one removed")
    check(json.load(open(os.path.join(dst, "versions-2026-11-19.json")))["rows"][0]["version"] == "v2.1.47",
          "the rows arrive intact")

sys.exit(1 if failures else 0)
