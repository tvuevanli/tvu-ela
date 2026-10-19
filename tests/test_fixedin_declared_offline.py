#!/usr/bin/env python3
"""The declared-version reading, offline: the lexical rules carried over from Helm's evidence engine, checked on the
comment shapes that produced wrong readings (MH-3215, MH-3418, MH-3675, MH-3750, MH-3599, MH-3330)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "fixedin"))
import fixedin as F  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# a fake image index so the docker rule is checked without the published map
F._IMAGES = {"tvu_live_transmit": [{"slug": "mds-mpegts-receiver", "gm_name": "Docker Mpegts Receiver", "process_type": "mpegts_receiver"},
                                   {"slug": "mds-mpegts-transmitter", "gm_name": "Docker Mpegts Transmitter", "process_type": "mpegts_transmitter"}],
             "tvurtc/output": [{"slug": "mds-ai-sender", "gm_name": "", "process_type": "ai_sender"}],
             "output": [{"slug": "mds-ai-sender", "gm_name": "", "process_type": "ai_sender"}]}

check("a bare MAJOR.MINOR is a release line", F.is_bare_line("2.1") and F.is_bare_line("v2.0") and not F.is_bare_line("2.1.72") and not F.is_bare_line("build 52"))
check("a trailing full stop is not part of a version", F.normalize_token("v3.0.30.") == "3.0.30")

b = "Deployed to QA-AWS3: ur-caller (mx-service) v2.1.72, branch release2.1"
pairs, via = F.resolve_pairs(b, F.VERSION_RX.findall(b), "")
check("MH-3750: the named service pairs with its full version", pairs == [("unified-streaming", "2.1.72")])
b = "fix note: UR Caller / mx-service，release2.1 线"
pairs, via = F.resolve_pairs(b, F.VERSION_RX.findall(b), "")
check("a release-line token alone is reported bare, not as a version", pairs and F.is_bare_line(pairs[0][1]))

b = "Released [Media Hub] frontend v2.2.110 and Unified Media Frontend v3.0.30."
pairs, via = F.resolve_pairs(b, F.VERSION_RX.findall(b), "")
check("MH-3675: two services in one comment are two pairs", sorted(pairs) == [("mediahub-frontend", "2.2.110"), ("unified-media-frontend", "3.0.30")])

b = "Env & Version:\nunified-media-frontend@3.0.5"
check("an explicit slug@version is read as written", F.resolve_pairs(b, F.VERSION_RX.findall(b), "") == ([("unified-media-frontend", "3.0.5")], "explicit token"))

b = "fix(service): headlessr起流前先探health再调startlive\nreleased ur-caller v1.0.613"
pairs, via = F.resolve_pairs(b, F.VERSION_RX.findall(b), "")
check("MH-3418: a service named in a commit subject is masked, the release wins", pairs == [("unified-streaming", "1.0.613")])

b = "API contract for the frontend (cc Summer) — released in [Mediahub] 2.1.12 + [Unified Resources Caller] 2.1.46"
pairs, via = F.resolve_pairs(b, F.VERSION_RX.findall(b), "")
check("MH-3458: a bare 'frontend' before its qualifier is not MediaHub's frontend", ("mediahub-frontend", "2.1.12") not in pairs)

d = F.resolve_docker("docker.tvunetworks.com/tvurtc/tvu_live_transmit:1.0.22  Fixed.", "the mpegts_receiver node restarts")
check("MH-3599: a docker image narrows to the service the ticket names", d == [("mds-mpegts-receiver", "tvu_live_transmit:1.0.22")])
d = F.resolve_docker("pushed tvu_live_transmit:1.0.22", "")
check("a shared image with nothing to narrow it names every service built from it", [s for s, _ in d] == ["mds-mpegts-receiver", "mds-mpegts-transmitter"])
check("a namespaced image resolves and is written bare", F.resolve_docker("output:v1.0.12.", "") == [("mds-ai-sender", "output:v1.0.12")])

check("an explicit negative verdict refutes", F.qa_refutes("验证结果：未修复 ❌ 3 Pass + 1 Fail"))
check("MH-3330: an incidental Pass tally does not mask the rejection", F.qa_refutes("验证结果：未修复 ❌\n16 项 Pass"))
check("a passing comment that says 'still' is not a refutation", not F.qa_refutes("验证通过 ✅ the earlier issue is still fixed"))
check("a loose re-failure token with no verdict line refutes", F.qa_refutes("还是有问题，切换后画面黑屏"))

roster = [{"name": "Dev One", "jira_name": "Dev One", "area": "app"}, {"name": "QA One", "jira_name": "QA One", "area": "qa"}, {"name": "Owner", "area": "engineering"}]
F.P.person_area = lambda r, who: next((p["area"] for p in r if p["name"] == who), "")
cs = [{"author": {"displayName": "Dev One"}, "created": "2026-09-11T10:00", "body": "Deployed to QA-AWS3: ur-caller v2.1.60"},
      {"author": {"displayName": "QA One"}, "created": "2026-10-11T10:00", "body": "验证结果：未修复 ❌"},
      {"author": {"displayName": "Dev One"}, "created": "2026-10-14T10:00", "body": "Deployed: media-hub-v4 v2.1.30, mediahub backend v2.1.30"},
      {"author": {"displayName": "Owner"}, "created": "2026-10-15T10:00", "body": "Closing; prod-3 runs unified-streaming v2.1.68"}]
F.P.adf_text = lambda b: b if isinstance(b, str) else ""
r = F.declared_from_comments(cs, "", roster)
check("a declaration post-dated by a QA refutation is left out, a later one stands", [x["value"] for x in r["declared"]] == ["mediahub-backend@2.1.30"] and r["suppressed_by_qa_refutation"] == 1)
check("the owner's closing comment is not a declaration", all(x["author"] != "Owner" for x in r["declared"]))

print("fixedin declared: all offline checks passed" if not failures else f"fixedin declared: {len(failures)} check(s) failed")
sys.exit(1 if failures else 0)
