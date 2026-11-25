#!/usr/bin/env python3
"""`ela publish lanes` gives every `lane` in the published lane json a `label` beside it — the lane's display label,
MediaHub's name first with the UR / J2N environment in brackets where the map names one — and writes lanes/README.md
saying so, so Helm renders the label verbatim. Runs on a fixed map in a temporary directory; no site is read."""
import json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "publish"))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
import publish  # noqa: E402 — the module under test
import release as R  # noqa: E402

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


R._MAP = {"lines": {"2.1": {"lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"},
                            "lane_for_slug": {"j2n": "daily-test2", "ur-portal": "daily-test2"}},
                    "2.0": {"lanes": {"qa": "qa-cn2", "daily": "daily-stage", "prod": "prod-8"},
                            "lane_for_slug": {"j2n": "daily-stage", "ur-portal": "daily-stage"}}},
          "regions": {"china": {"ur": {"envs": {"cn2": "prod2"}}, "lanes": {"prod-2-china": {"shown": "CN Prod2", "line": "2.1"}}}}}
label = publish.lane_label_of()
check([label(l) for l in ("daily-wed", "prod-3", "qa-cn3", "prod-2-china", "daily-stage", "qa-cn2")] ==
      ["daily-wed (UR test2)", "prod-3 (UR/J2N Prod 3)", "QA-AWS3", "CN Prod2 (UR/J2N cn2)", "daily-stage (UR/J2N Stage)", "QA-AWS2"],
      "the label: MediaHub's name, the UR environment in brackets where the map names it, never the file token")

tl = {"lane": "daily-wed", "lane_build": "20261120", "rows": {"MH-1": {"verdict": "pass"}}, "shown": "Daily WED"}
out = json.loads(publish.with_labels(json.dumps(tl), "test-list-daily-wed.json", label))
check(out["label"] == "daily-wed (UR test2)" and list(out)[:2] == ["lane", "label"] and out["shown"] == "Daily WED"
      and out["rows"] == tl["rows"], "a test list gains its lane's label beside `lane`; the rest is unchanged")
dl = {"line": "2.1", "lane": "qa-cn3", "rows": [{"key": "MH-1"}], "env": [{"lane": "prod-2-china", "id": "diff-x"}]}
out = json.loads(publish.with_labels(json.dumps(dl), "dev-list-2.1.json", label))
check(out["label"] == "QA-AWS3" and out["env"][0]["label"] == "CN Prod2 (UR/J2N cn2)" and "label" not in out["rows"][0],
      "a dev list: the document and each row of a top-level list that names a lane")
again = publish.with_labels(publish.with_labels(json.dumps(dl), "dev-list-2.1.json", label), "dev-list-2.1.json", label)
check(json.loads(again) == out, "labelling twice changes nothing")
check(publish.with_labels("# The lanes", "lanes.md", label) == "# The lanes" and publish.with_labels("{", "x.json", label) == "{"
      and publish.with_labels('{"lane": "prod-3"}', "x.json", None) == '{"lane": "prod-3"}',
      "a page, a json that does not parse, or no label function: the text as it was")

with tempfile.TemporaryDirectory() as t:
    runner, dst = os.path.join(t, "runtime", "runner"), os.path.join(t, "published", "lanes")
    os.makedirs(runner)
    json.dump({"date": "2026-11-25", "rows": [{"service": "mediahub-backend", "lane": "prod-3", "version": "v2.1.47"}]},
              open(os.path.join(runner, "versions-2026-11-25.json"), "w"))
    check(publish.publish_versions({"runtime": os.path.join(t, "runtime")}, dst, label) == "published versions-2026-11-25.json"
          and json.load(open(os.path.join(dst, "versions-2026-11-25.json")))["rows"][0]["label"] == "prod-3 (UR/J2N Prod 3)",
          "the versions file's rows carry the label too")
check("`label`" in publish.LANES_README and "verbatim" in publish.LANES_README, "the README beside the files documents the field")

sys.exit(1 if failures else 0)
