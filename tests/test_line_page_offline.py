#!/usr/bin/env python3
"""The line page, offline: one release line as one page from local files — each lane named MediaHub-first with its UR
environment in brackets, its build and QA's word, a lane ahead of its upstream said why, two lanes on the same versions
as one row, a Can't read line, the next promotion, the docker images that differ, one line per build with its detail
folded, the history; at most 800 words above the fold and every key linked once the vault's linker has run."""
import datetime, json, os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import release as R  # noqa: E402
import line as LP  # noqa: E402
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

R._MAP = {"lines": {"2.1": {"lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}, "decided": "yes",
                            "lane_for_slug": {"j2n": "daily-test2", "ur-portal": "daily-test2"}}},
          "regions": {"china": {"ur": {"envs": {"cn2": "prod2"}}, "lanes": {"prod-2-china": {"shown": "CN Prod2", "line": "2.1"}}}}}
TODAY = datetime.date(2026, 11, 20)


def write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False))


def rec(build, date, services, notes=""):
    return {"line": "2.1", "lane": "qa-cn3", "lane_name": "QA-AWS3", "build": str(build), "date": date, "at": date + "T18:00:00+08:00",
            "services": services, **({"notes": notes} if notes else {})}


def svc(name, frm, to, why, keys):
    return {"service": name, "from": frm, "to": to, "for": why, "keys": keys}


def row(lane, service, version, host="prod", state=None):
    return {"lane": lane, "service": service, "version": version, "host": host, "state": state}


check("lanes are named MediaHub-first, the UR environment in brackets",
      [LP.lane_label(l) for l in ("qa-cn3", "daily-wed", "prod-3", "prod-2-china", "daily-stage", "qa-cn2", "prod-8")] ==
      ["QA-AWS3", "daily-wed (UR test2)", "prod-3 (UR/J2N Prod 3)", "CN Prod2 (UR/J2N cn2)", "daily-stage", "QA-AWS2", "prod-8 (UR/J2N Prod 8)"])

with tempfile.TemporaryDirectory() as tmp:
    reports, runtime = os.path.join(tmp, "reports"), os.path.join(tmp, "runtime")
    rd = os.path.join(reports, "releases", "2.1")
    write(os.path.join(rd, "2026-11-18-build-98-to-qa-aws3.json"),
          rec(98, "2026-11-18", [svc("MediaHub Backend", "2.1.46", "2.1.47", "Akamai static IP pool table", ["MH-4052"]),
                                 svc("UR Caller", "2.1.97", "2.1.98", "Akamai static IP from a managed pool", ["MH-4052"])]))
    write(os.path.join(rd, "2026-11-19-build-99-to-qa-aws3.json"),
          rec(99, "2026-11-19", [svc("MediaHub Backend", "2.1.47", "2.1.48", "Self-managed EIP admin backend", ["MH-4065", "MH-4016"]),
                                 svc("UR Caller", "2.1.98", "2.1.99", "Self-managed EIP pool rules", ["MH-4065"])], notes="Build 99 is under test."))
    write(os.path.join(rd, "2026-11-17-build-95-to-qa-aws3.json"),
          rec(95, "2026-11-17", [svc("MediaHub Backend", "2.1.45", "2.1.46", "Source list survives one bad device record", []),
                                 svc("UR Caller", "2.1.94", "2.1.95", "Destination URL protocol checked", ["MH-3967"])]))
    old = rec(80, "2026-10-29", [svc("UR Caller", "2.1.79", "2.1.80", "An old build", ["MH-3855"])])
    write(os.path.join(rd, "2026-10-29-build-80-to-qa-aws3.json"), old)
    snap = {"rows": [row("qa-cn3", "mediahub-backend", "v2.1.48", "mail", "built"), row("qa-cn3", "unified-streaming", "v2.1.99", "mail", "built"),
                     row("daily-wed", "mediahub-backend", "v2.1.46 build278 2026-11-17 03:11:40"), row("daily-wed", "unified-streaming", "v2.1.95 build386"),
                     row("prod-3", "mediahub-backend", "v2.1.47 build279 2026-11-18 08:06:12"), row("prod-3", "unified-streaming", "v2.1.98 build389"),
                     row("prod-2-china", "orchestration", "4.0.208", "mail", "requested")]}
    write(os.path.join(runtime, "runner", "versions-2026-11-18.json"), dict(snap, rows=[r for r in snap["rows"] if r["lane"] != "prod-3"]))
    write(os.path.join(runtime, "runner", "versions-2026-11-20.json"), snap)
    write(os.path.join(runtime, "runner", "qa-tested.json"), {
        "a": {"lane": "qa-cn3", "service": "mediahub-backend", "version": "v2.1.47 build279", "at": "2026-11-19T19:10:45+08:00", "verdict": "partial",
              "subject": "Summary Test Report for [Release Mediahub QA-AWS3] For 2.1 Release build 98 on 11-19"},
        "b": {"lane": "qa-cn3", "service": "mediahub-backend", "version": "v2.1.46 build278", "at": "2026-11-17T19:07:24+08:00", "verdict": "pass",
              "subject": "Summary Test Report for [Release Mediahub QA-AWS3] For 2.1 Release build 95 on 11-17"},
        "c": {"lane": "prod-2-china", "service": "mediahub-backend", "version": "v2.1.26 build256", "at": "2026-11-13T10:00:00+08:00", "verdict": "pass",
              "subject": "CN test report"}})
    write(os.path.join(reports, "promote", "2.1-qa-daily.json"), {
        "generated_at": "2026-11-20T00:20:55Z",
        "delta": {"services": [{"service": "mediahub-backend", "relation": "from_ahead",
                                "commits": [{"sha": "a1", "keys_in_subject": ["MH-4052"]}, {"sha": "a2", "keys_in_subject": ["MH-4065"]},
                                            {"sha": "a3", "keys": ["MH-4016"]}]}]},
        "tickets": {"tickets": [{"key": k, "exists": True, "summary": f"summary of {k}"} for k in ("MH-4052", "MH-4065", "MH-4016")]},
        "evidence": {"keys": {"MH-4052": {"verdict": "pass", "items": [{"verdict": "pass", "when": "2026-11-19T11:10"}]},
                              "MH-4065": {"verdict": "fail", "items": [{"verdict": "fail", "when": "2026-11-19T12:00"}]}}}})
    write(os.path.join(reports, "promote", "pending.json"), {
        "2.1|daily-wed|prod-3": {"line": "2.1", "from": "daily-wed", "to": "prod-3", "closed": False,
                                 "candidate": {"label": "Wednesday (build 78) → prod-3", "versions": {"mediahub-backend": {"version": "2.1.40+270"}}}}})
    write(os.path.join(reports, "docker", "candidates.json"), {"candidates": [
        {"image": "mixer", "version": "1.0.36", "verdict": "under-test", "report": None, "lanes": [
            {"line": "2.1", "lane": "qa-cn3", "state": "unread"},
            {"line": "2.1", "lane": "daily-wed", "state": "behind", "have": ["1.0.35"], "gm": ["Docker Switcher"]},
            {"line": "2.1", "lane": "prod-3", "state": "at", "have": ["1.0.36"], "gm": ["Docker Switcher"]}]},
        {"image": "copier", "version": "1.0.90", "verdict": "under-test", "report": None, "lanes": [
            {"line": "2.1", "lane": "daily-wed", "state": "at", "have": ["1.0.90"], "gm": ["Docker Srt Copier"]},
            {"line": "2.1", "lane": "prod-3", "state": "at", "have": ["1.0.90"], "gm": ["Docker Srt Copier"]}]}]})
    write(os.path.join(reports, "releases", "docker-versions.jsonl"),
          json.dumps({"image": "mixer", "version": "1.0.36", "at": "2026-11-19 16:41", "source": "mail x", "by": "a developer",
                      "subject": "Project mixer build 9 & docker.tvunetworks.com/tvurtc/mixer:1.0.36 release", "claims": [{"key": "MH-3984"}]}) + "\n" +
          json.dumps({"image": "mixer", "version": "1.0.35", "at": "2026-11-01 10:00", "source": "mail y", "by": "a developer",
                      "subject": "Project mixer build 8 & docker.tvunetworks.com/tvurtc/mixer:1.0.35 release", "claims": []}) + "\n")
    def issue(key, status, cat, labels, assignee=True, due=None, fixed=None):
        f = {"summary": f"summary of {key}", "status": {"name": status, "statusCategory": {"key": cat}}, "labels": labels,
             "assignee": {"displayName": "a developer"} if assignee else None, "duedate": due, "customfield_11252": fixed}
        write(os.path.join(runtime, "facts", "jira", "issues", f"{key}.json"), {"key": key, "fields": f, "updated": "2026-11-19T10:00:00Z"})
    issue("MH-4052", "Review", "indeterminate", ["release:mh-2.1"], due="2026-11-21", fixed="mediahub-backend@2.1.47")
    issue("MH-4065", "In Progress", "indeterminate", ["release:mh-2.1"], assignee=False)
    issue("MH-3855", "Done", "done", ["release:mh-2.1", "release:mh-2.0"], fixed="unified-streaming@2.1.80")
    issue("MH-9999", "Done", "done", ["release:mh-2.0"])
    R._MAP["lines"]["2.1"]["label"] = "release:mh-2.1"
    notes = [{"rel": "releases/2.1/history/2026-11-17-promote-daily-wed-to-prod-3.md", "title": "MH 2.1 · Wednesday → Prod 3", "date": "2026-11-17", "status": "done"},
             {"rel": "releases/2.1/2026-11-12-sync-prod-3-to-cn-prod-2.md", "title": "MediaHub 2.1 · prod-3 → CN Prod2", "date": "2026-11-12", "status": "live"}]
    d = LP.gather("2.1", reports, runtime, TODAY, notes)
    page = LP.render(d)
    now = page.split("## Now")[1].split("## Next promotion")[0]
    check("Now: one row per lane, MediaHub-first, with its build",
          "| QA-AWS3 | build 99 |" in now and "| daily-wed (UR test2) | build 95 |" in now and "| prod-3 (UR/J2N Prod 3) | build 98 |" in now
          and "| CN Prod2 (UR/J2N cn2) |" in now)
    check("QA's word: the QA lane's build without a report is under test; a lane's version QA reported shows its verdict",
          re.search(r"\| QA-AWS3 \| build 99 \| 11-19 \| (under test|no report on build 99)", now) is not None
          and "| daily-wed (UR test2) | build 95 | 11-18 | pass 11-17; 1 unreported |" in now)
    check("a lane ahead of its upstream says why: prod-3 took build 98 past the daily lane",
          "prod-3 is ahead of daily-wed on MediaHub Backend 2.1.47 (theirs 2.1.46), UR Caller 2.1.98 (theirs 2.1.95): taken straight from QA-AWS3 build 98, past the daily lane" in now)
    cant = next((l for l in now.splitlines() if l.startswith("**Can't read:**")), "")
    check("one Can't read line names each gap in 15 words or fewer; why each could not be read is folded under it",
          cant == "**Can't read:** QA-AWS3, CN Prod2, daily → prod promote report, docker on QA-AWS3, titles of 3 tickets." and len(cant.split()) <= 17
          and "> [!note]- Why each could not be read\n> - **QA-AWS3**: QA-AWS3: the QA host is not read" in now
          and "> - **daily → prod promote report**: none stored; `ela promote report 2.1 daily prod` writes it" in now)
    table = [l for l in now.splitlines() if l.startswith("| ") and "---" not in l][1:]
    check("the lane table is four short cells a lane, QA's word in six words or fewer; the per-service exceptions folded",
          all(len(l.strip("| ").split(" | ")) == 4 and len(l.strip("| ").split(" | ")[3].split()) <= 6 for l in table)
          and "> [!note]- Per service: builds, QA and the lane ahead" in now
          and "> - prod-3 is ahead of daily-wed on MediaHub Backend 2.1.47 (theirs 2.1.46)" in now)
    check("the lane ahead of its upstream is one short sentence in the head", "\nprod-3 is ahead of daily-wed: build 98 went straight to it (a hotfix).\n" in now)
    check("the head passes the presentation lint", V.present_lint("releases/2.1/2.1.md", page, generated=True) == [])
    nxt = page.split("## Next promotion")[1].split("## Docker")[0]
    check("Next promotion: the candidate build, what is ready, what blocks it, the decision",
          "**QA-AWS3 build 99 → daily-wed (UR test2):** 3 tickets daily-wed does not run; 1 QA passed, 1 failed, 1 without a QA pass" in nxt
          and "**Ready:** MH-4052" in nxt and "**Blocks:** MH-4065" in nxt and "QA fail 11-19" in nxt and "**Decision:** move QA-AWS3 build 99 to daily-wed" in nxt)
    check("a promotion record its target already passed is said to be past under History, not in the head",
          "“Wednesday (build 78) → prod-3” is past" in page.split("## History")[1] and "is past" not in nxt)
    dock = page.split("## Docker")[1].split("## Builds")[0]
    check("Docker: only the image that differs between lanes, each version with its QA report or none and what it changed",
          "- **mixer** · daily-wed 1.0.35 vs prod-3 1.0.36 · QA report on 1.0.36: no" in dock and "copier" not in dock
          and "> - **mixer** (Docker Switcher): 1.0.36: no QA report; MH-3984" in dock and "1.0.35: no QA report; released 11-01, no ticket named" in dock)
    builds = page.split("## Builds")[1].split("## History")[0]
    lines = [l for l in builds.splitlines() if l.startswith("- ")]
    check("Builds: one line per build of the last two weeks, newest first, each with a block id; the detail folded",
          [re.search(r"build (\d+)", l).group(1) for l in lines] == ["99", "98", "95"] and lines[0].endswith("^build-99")
          and "> [!note]- Build 99: what each service carries" in builds and "> **MediaHub Backend** 2.1.47 → 2.1.48 · Self-managed EIP admin backend" in builds
          and "> - MH-4065 summary of MH-4065" in builds and "> Build 99 is under test." in builds)
    check("a build older than two weeks is folded, not dropped", "> [!note]- 1 older build" in builds and "build 80" in builds)
    check("a service heading inside the fold is set apart, never read as part of the ticket list above it",
          "> - MH-4016 (not in the fact store)\n>\n> **UR Caller**" in builds)
    hist = page.split("## History")[1]
    check("History: one line per promotion or deploy, linking its note, newest first",
          hist.index("2026-11-17-promote-daily-wed-to-prod-3") < hist.index("2026-11-12-sync-prod-3-to-cn-prod-2")
          and "[[releases/2.1/history/2026-11-17-promote-daily-wed-to-prod-3|MH 2.1 · Wednesday → Prod 3]] · done" in hist)
    tix = page.split("## Tickets")[1].split("## History")[0]
    check("Tickets: the line's labelled tickets only, by state, folded, with a fields-health figure naming what is missing",
          "3 tickets labelled release:mh-2.1 · fields health 33% (1 of 3 with every field right; missing:" in tix
          and "assignee 1" in tix and "due date 1" in tix and "label 1" in tix and "MH-9999" not in tix
          and "> [!note]- In Progress · 1" in tix and "> [!note]- Review · 1" in tix and "> [!note]- Done · 1" in tix
          and tix.index("In Progress ·") < tix.index("Review ·") < tix.index("Done ·")
          and "| Review | a developer | 11-21 | prod-3 | mediahub-backend@2.1.47 |" in tix)
    check("at most 800 words above the fold", len(V.outside_folds(page).split()) <= 800)
    linked, _ = V.link_keys(page, "https://jira.example/browse".rsplit("/browse", 1)[0], None)
    check("every Jira key a link once the vault's linker has run", not V.bare_keys(linked) and "[MH-4052](https://jira.example/browse/MH-4052)" in linked)

    # two lanes on the same versions are one row
    same = dict(snap, rows=[r for r in snap["rows"] if r["lane"] != "prod-3"] +
                [dict(r, lane="prod-3") for r in snap["rows"] if r["lane"] == "daily-wed"])
    write(os.path.join(runtime, "runner", "versions-2026-11-20.json"), same)
    page2 = LP.render(LP.gather("2.1", reports, runtime, TODAY))
    check("two lanes running the same versions are one row", "| daily-wed (UR test2) = prod-3 (UR/J2N Prod 3) | build 95 |" in page2
          and "ahead of" not in page2.split("## Next promotion")[0])

print(f"\n{len(failures)} failure(s)" if failures else "\nall passed")
sys.exit(1 if failures else 0)
