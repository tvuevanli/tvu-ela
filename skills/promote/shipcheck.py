#!/usr/bin/env python3
"""The release version against the version proven on the source lane: a service that ships a build the source lane
does not run carries commits no lane test has seen, and each one needs its own QA evidence.

Why: on 2026-11-09 the release named UR Caller 2.1.87 for prod-3 while daily-wed ran 2.1.85; MH-3961 and MH-3966
(twice) sat between them, and the Wed test and QA's verdicts on 2.1.85 were being read as if they covered 2.1.87.

Pure functions; promote.py does the reads (Jenkins, git, Jira) and passes them in:

  resolve(name, slugs, aliases)        a service as the owner writes it (UR Caller, ur-caller, unified-streaming) → slug
  gap(service, source, ship, commits, qa, at_least)
                                       the commits between the source lane's build and the shipped one, their tickets,
                                       and for each ticket the QA verdicts run on a build that carries it
"""

# The services as the owner, the release note and Slack name them. The published catalogue does not yet carry these
# names (a draft for elak's map is in <runtime>/drafts); until it does, this table is the one place they are written.
NAMES = {"unified-streaming": "UR Caller", "mediahub-backend": "MediaHub backend", "mediahub-frontend": "MediaHub frontend",
         "unified-media-backend": "Unified Media backend", "unified-media-frontend": "Unified Media frontend"}
JOB_ALIASES = {"ur-caller": "unified-streaming", "media-hub-v4": "mediahub-backend"}
COVERING = ("pass", "partial")   # a partial pass is shown with its word; "accepted" ships nothing, so covers nothing


def name(slug):
    return NAMES.get(slug, slug)


def resolve(text, slugs, aliases=None):
    t = (text or "").strip().lower().replace("_", "-")
    if t in slugs:
        return t
    table = {**JOB_ALIASES, **{k.lower(): v for k, v in (aliases or {}).items()},
             **{v.lower().replace(" ", "-"): k for k, v in NAMES.items()}}
    s = table.get(t) or table.get(t.replace(" ", "-"))
    return s if s in slugs else None


def carries(text, target, parse, cmp):
    """True when a version text (a QA environment block's, a panel's) is at or past the ship build. A version written
    without its build compares on the label alone: QA's "2.1.87" is the 2.1.87 build."""
    pv = parse(text) if text else None
    if not (pv and target):
        return False
    return cmp(pv, target if pv[4] else tuple(target[:4]) + (0,)) >= 0


def gap(service, source, ship, commits, qa, at_least):
    """source/ship: {version, build, sha}; commits: [{sha, subject, keys}] in source..ship; qa: key → [QA items with
    verdict, who, when, env_lane, env_versions]; at_least(version_text) → True when that version carries the ship build.
    Returns the record and the tickets no QA verdict on a carrying build covers."""
    by_key = {}
    unticketed = []
    for c in commits:
        if not c.get("keys"):
            unticketed.append(c)
        for k in c.get("keys") or []:
            by_key.setdefault(k, []).append(c)
    tickets = []
    for k, cs in sorted(by_key.items()):
        items = [i for i in qa.get(k) or [] if i.get("area", "qa") == "qa" and i.get("verdict")]
        on_ship = [i for i in items if i["verdict"] in COVERING and at_least(((i.get("env_versions") or {}).get(service) or ""))]
        older = [i for i in items if i not in on_ship]
        tickets.append({"key": k, "commits": [c["sha"] for c in cs], "subjects": [c["subject"][:80] for c in cs],
                        "covered_by": [{"who": i.get("who"), "when": i.get("when"), "verdict": i["verdict"], "lane": i.get("env_lane"),
                                        "version": (i.get("env_versions") or {}).get(service)} for i in on_ship],
                        "not_covering": [{"who": i.get("who"), "when": i.get("when"), "verdict": i["verdict"], "lane": i.get("env_lane"),
                                          "version": (i.get("env_versions") or {}).get(service) or "no environment block"} for i in older]})
    uncovered = [t["key"] for t in tickets if not t["covered_by"]]
    return {"service": service, "name": name(service), "source": source, "ship": ship, "commits": len(commits),
            "tickets": tickets, "unticketed": [{"sha": c["sha"], "subject": c["subject"][:80]} for c in unticketed],
            "uncovered": uncovered}


def words(g, from_lane):
    """The finding's text: what ships, what the source lane proves, what lies between and who has tested it."""
    head = (f"{g['name']} ships {g['ship']['version']} (build {g['ship'].get('build')}) but {from_lane} runs "
            f"{g['source']['version']} (build {g['source'].get('build')}): {g['commits']} commit(s) between no lane test on {from_lane} covers")
    parts = []
    for t in g["tickets"]:
        n = len(t["commits"])
        cov = ("QA on a carrying build: " + ", ".join(f"{c['who']} {str(c['when'])[:10]} {c['verdict']} on {c['version']}" for c in t["covered_by"])
               if t["covered_by"] else "no QA on a build that carries it"
               + (" (QA seen only on " + ", ".join(sorted({str(c['version']) for c in t["not_covering"]})) + ")" if t["not_covering"] else ""))
        parts.append(f"{t['key']}{f' ×{n}' if n > 1 else ''} — {cov}")
    if g["unticketed"]:
        parts.append(f"{len(g['unticketed'])} commit(s) with no ticket: " + "; ".join(f"{c['sha']} {c['subject'][:40]}" for c in g["unticketed"][:3]))
    return head + ". " + " · ".join(parts)
