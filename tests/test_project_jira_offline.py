#!/usr/bin/env python3
"""A Jira project's page, offline: an open kind:project ticket in the fact store gets one page projects/<key>-<slug>.md,
its head kept as written, Where it stands written from the store; a project is one page or, grown, a folder."""
import datetime, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "vault"))
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

def issue(key, summary, labels, cat="indeterminate", subtasks=()):
    return {"key": key, "updated": "2026-11-10T09:12:17+00:00", "read_at": "2026-11-10T17:12:29+08:00",
            "fields": {"summary": summary, "labels": labels, "assignee": {"displayName": "Carrier One"},
                       "status": {"name": "In Progress", "statusCategory": {"key": cat}}, "statuscategorychangedate": "2026-11-10T01:00:00.000+0000",
                       "duedate": "2026-12-01", "subtasks": [{"key": k, "fields": {"summary": s, "status": {"name": "Backlog"}}} for k, s in subtasks]}}

today = datetime.date(2026, 11, 11)
with tempfile.TemporaryDirectory() as t:
    d = os.path.join(t, "facts", "jira", "issues"); os.makedirs(d)
    for i in (issue("MH-1", "CSC control from HTTP to MQTT via mqtt-gateway", ["kind:project"], subtasks=[("MH-2", "[UR] loopback")]),
              issue("MH-3", "A bug", ["kind:bug"]), issue("MH-4", "Done project", ["kind:project"], cat="done")):
        json.dump(i, open(os.path.join(d, i["key"] + ".json"), "w"))
    tickets = V.jira_projects(t)
    check("only open kind:project tickets are projects", [x["key"] for x in tickets] == ["MH-1"]
          and tickets[0]["owner"] == "Carrier One" and tickets[0]["subtasks"][0][0] == "MH-2")
    key = V.jira_project_key(tickets[0])
    check("its page key is the ticket and a short slug", key.startswith("mh-1-csc-control") and len(key) <= 40)
    v = os.path.join(t, "v"); os.makedirs(os.path.join(v, "projects", "sb"))
    check("one page, or a folder once it has one", V.project_path(v, key) == f"projects/{key}.md" and V.project_path(v, "sb") == "projects/sb/sb.md")
    n = V.project_note(key, V.jira_project_page(tickets[0], today), v, [], today, "https://jira.example", tickets[0])
    page = n.front_text + n.head + n.tail
    check("the head is kept: next step and open questions, above Where it stands",
          page.index("## Next step") < page.index("## Open questions") < page.index("## Where it stands") < page.index("## Waiting for your word"))
    check("Where it stands: the carrier, the status and since when, each sub-task linked, when Jira was read",
          "Carried by Carrier One · In Progress since 2026-11-10" in page and "[MH-2](https://jira.example/browse/MH-2) [UR] loopback · Backlog" in page
          and "*Read from Jira 2026-11-10T17:12.*" in page)
    check("the ticket's due date is the deadline until the page names one", "2026-12-01" in page.split("## Deadline")[1])
    check("a head edit survives: the head is what is above Where it stands",
          V.project_head(V.split_front(page.replace("Not written yet: one line, with its date.", "Ship the gateway, 11-20."))[1])[0].count("Ship the gateway") == 1)
    check("a single page passes the type lint, a stray one does not", V.type_lint(f"projects/{key}.md", "project") is None
          and V.type_lint("projects/a/b.md", "project") is not None)
    open(os.path.join(v, "projects", key + ".md"), "w").write(page)
    check("a note may name a single-page project", V.project_lint("x.md", {"project": key}, v) is None
          and V.project_lint("x.md", {"project": "nope"}, v) is not None)
    check("a slug is two to four whole words, never a phrase cut mid-way",
          V.project_slug("Encoding Level: Auto as the default option, all supported fixed levels (H.264/H.265)") == "encoding-level-auto"
          and V.project_slug("Destination-side CSC, with and without mixer") == "destination-side-csc"
          and V.project_slug("[UR] Start CSC loopback-only without auth token") == "start-csc-loopback-only")
    check("a page is that ticket's when its keys lead with it", V.page_ticket_key('---\nkeys: "MH-1 MH-9"\n---\n# x\n') == "MH-1"
          and V.page_ticket_key('---\ntype: "project"\n---\n# x\n') is None)
    check("deadline is optional for a ticket project, required of outside work",
          not any("deadline" in x for x in V.spec_lint(f"projects/{key}.md", page.replace('deadline: "2026-12-01"\n', "")))
          and any("missing" in x and "deadline" in x for x in V.spec_lint("projects/sb/sb.md", '---\ntitle: "SB"\ntype: "project"\ndate: "2026-11-01"\nsource: "vault"\n---\n# SB\n')))
    # the desk's hand-named page leads its keys with MH-1: the sync adopts it and makes no second page
    open(os.path.join(v, "projects", key + ".md"), "w").write("")
    os.remove(os.path.join(v, "projects", key + ".md"))
    open(os.path.join(v, "projects", "mh-1-by-hand.md"), "w").write(page)
    s = {"vault": v, "runtime": t, "reports": os.path.join(t, "r"), "elak": None}
    os.makedirs(os.path.join(t, "r", "ela"))
    pages = V.project_pages(v)
    paged = {k for text in pages.values() for k in V.KEY_RX.findall(V.props_of(V.split_front(text)[0]).get("keys") or "")}
    check("a hand-named page leading with the ticket is its page: no second one", "MH-1" in paged and list(pages) == ["mh-1-by-hand"])
    asked = page.replace("None yet. Each is a box", "- [ ] Who carries it? · ela proposes: the app owner\n\nEach is a box")
    pn = V.project_note("mh-1-by-hand", asked, v, [], today, "", tickets[0])
    c = V.ask_candidates(today, [], [pn])
    check("the page's open questions show on today.md as one line linking the page",
          len(c) == 1 and c[0]["link"] == "projects/mh-1-by-hand" and c[0]["text"].startswith("1 open question on MH-1 "))
print("project jira: all offline checks passed" if not failures else f"project jira: {len(failures)} failed")
sys.exit(1 if failures else 0)
