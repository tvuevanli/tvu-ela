#!/usr/bin/env python3
"""`publish.redact` replaces an address that is the host of a URL even when the URL's path looks like a
version (`/v1/`), and keeps a dotted version number on a version line. Pure function; nothing is read or
written."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "publish"))
import publish  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


check(publish.redact("default: https://10.1.2.3:4318/v1/traces") == "default: https://<ip>:4318/v1/traces",
      "a URL host is redacted although its path carries /v1/")
check(publish.redact("version: 1.0.0.12") == "version: 1.0.0.12",
      "a dotted version on a version line is kept")

if failures:
    print(f"publish redact: {len(failures)} failed"); sys.exit(1)
print("publish redact: all cases pass")
