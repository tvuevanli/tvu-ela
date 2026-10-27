#!/usr/bin/env python3
"""release create, offline: the write guard, the name grammar, tag matching, the description and the lane order.
Nothing here reaches userservice; create is never called."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
import release as R  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


W = R.write_refused
check("the only write is create, on prod", W("/userGroup/user-group/tagBundle/create", "prod") is None)
check("create is refused off prod", W("/userGroup/user-group/tagBundle/create", "qa") is not None)
check("delete, update and bind are refused, by path", all(W(p, "prod") for p in (
    "/userGroup/user-group/tagBundle/delete?bundleId=1", "/userGroup/user-group/tagBundle/update", "/userGroup/user-group/tag/bind",
    "/userGroup/user-group/tagBundle/batchRemove", "/userGroup/user-group/service/switchTag", "/userGroup/user-group/tag/save")))
check("reads pass, the POSTed page read included", all(W(p, "prod") is None for p in (
    "/userGroup/user-group/tagBundle/page", "/userGroup/user-group/tagBundle/getDetail?bundleId=1",
    "/userGroup/user-group/tag/getTagVersionList?serviceId=x", "/userGroup/user-group/service/list?showInternalFlag=true")))
calls = []
R.http = lambda *a, **k: calls.append(a) or (200, {})
us = object.__new__(R.US); us.kind, us.host, us.sid, us.env_file = "prod", "https://h", "s", None
try:
    us.call("/userGroup/user-group/tagBundle/delete?bundleId=1"); refused = False
except SystemExit:
    refused = True
check("US.call stops a refused path before any request", refused and calls == [])

C = lambda n: R.name_class(n, "mh2.1@")  # noqa: E731
check("daily names", C("mh2.1@daily-wed-s1-d45") == "daily" and C("mh2.1@stage-s4-d19") == "daily")
check("prod names", C("mh2.1@rc-s2-d8") == "prod" and C("mh2.1@ga-s1-d1") == "prod")
check("official names", C("MediaHub 2.1.15") == "official" and C("MediaHub 2.1.14 (Build Version Emission)") == "official"
      and C("MediaHub 2.0 rc11") == "official")
check("anything else is refused: no temporary form yet", C("mh2.1@tmp-encoder") is None and C("mh2.0@daily-wed-s1-d45") is None
      and C("mh2.1@daily-wed-d45") is None)
check("the next name follows the base", R.next_name("mh2.1@daily-wed-s1-d45") == "mh2.1@daily-wed-s1-d46"
      and R.next_name("MediaHub 2.1.15") == "MediaHub 2.1.16" and R.next_name("MediaHub 2.1.14 (Build Version Emission)") == "MediaHub 2.1.15"
      and R.next_name("MediaHub 2.0 rc11") == "MediaHub 2.0 rc12")

tags = [{"id": "a", "tagName": "1.0.51"}, {"id": "b", "tagName": "1.0.56"}, {"id": "c", "tagName": "default Production2"},
        {"id": "d", "tagName": "1.0.56-hotfix"}]
check("a version matches its one tag", R.match_tag(tags, "1.0.51")[0]["id"] == "a")
check("an exact name wins over a token match", R.match_tag(tags, "1.0.56")[0]["id"] == "b")
t, near = R.match_tag(tags, "1.0.60")
check("no match names the nearest tags", t is None and "1.0.51" in near)
two = [{"id": "x", "tagName": "v2 1.0.7"}, {"id": "y", "tagName": "1.0.7 old"}]
t, near = R.match_tag(two, "1.0.7")
check("two candidates are refused and listed", t is None and sorted(near) == ["1.0.7 old", "v2 1.0.7"])

check("the description is the diff", R.describe([{"service": "Docker Encoder", "from": "1.0.51", "to": "1.0.56"}], [], []) == "Docker Encoder 1.0.51 → 1.0.56"
      and R.describe([], [{"service": "Docker X", "version": "1.0.1"}], [{"service": "Docker Y", "version": "2"}]) == "add Docker X 1.0.1; drop Docker Y")

new = {"Docker Encoder": "1.0.56", "Docker Copier": "1.0.82", "Docker Scope": "default Production2", "Docker Mixer": "2.0.1"}
nb = {"qa": {"Docker Encoder": "1.0.55", "Docker Copier": "1.0.85", "Docker Mixer": "1.9.0"},
      "prod": {"Docker Encoder": "1.0.51", "Docker Copier": "1.0.83", "Docker Scope": "default Production4"}}
warns, und = R.order_warnings(new, "daily", nb)
says = sorted(w["says"] for w in warns)
check("a daily bundle above QA or below prod is warned", says == ["Docker Copier 1.0.82 is below prod 1.0.83", "Docker Encoder 1.0.56 is above qa 1.0.55"])
check("another series or a named tag is undetermined, never an inversion", und == 2 and not any("Mixer" in s or "Scope" in s for s in says))
warns, _ = R.order_warnings({"Docker Encoder": "1.0.57"}, "official", {"daily": {"Docker Encoder": "1.0.56"}})
check("an official bundle above daily is warned", [w["says"] for w in warns] == ["Docker Encoder 1.0.57 is above daily 1.0.56"])
sys.exit(1 if failures else 0)
