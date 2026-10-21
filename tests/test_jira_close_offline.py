#!/usr/bin/env python3
"""The close bundle's pure parts, offline: the lifecycle plan, mention resolution against a fake roster, and the
two-register ADF (short part as paragraphs, the part after a `---` line collapsed, `@name` as a mention node)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "jira"))
import jira as J  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# lifecycle plan: Jira offers only the current status's transitions, so the plan is the knowledge; the walk is live
check("Backlog → Done walks three hops", J.plan_path("Backlog", "Done") == ["Backlog", "In Progress", "Review", "Done"])
check("Review → Done is one hop", J.plan_path("Review", "Done") == ["Review", "Done"])
check("a status off the lifecycle has no plan", J.plan_path("Blocked", "Done") is None)
check("a plan never walks backwards", J.plan_path("Review", "Backlog") is None)
check("case and spacing do not matter", J.plan_path("in progress", "DONE") == ["In Progress", "Review", "Done"])

# mentions: exactly one roster person with a Jira id, else refused
class _T:
    @staticmethod
    def find(people, q):
        q = q.lower()
        return [p for p in people if p["name"].lower().split()[0] == q or p["name"].lower() == q]
J._TEAM, J._PEOPLE = _T, [{"name": "Erin Zhang", "jira": "acc-erin"}, {"name": "Andy Zhao", "jira": "acc-andy"},
                          {"name": "Robin Wu", "jira": ""}, {"name": "Alice Wang", "jira": "acc-alice"}, {"name": "Alice Li", "jira": "acc-alice2"}]
found, unresolved = J.resolve_mentions("@erin please verify; cc @andy and @robin, @alice, @nobody")
check("known first names resolve to account ids", found == {"erin": ("acc-erin", "Erin Zhang"), "andy": ("acc-andy", "Andy Zhao")})
check("a person without a Jira id, an ambiguous name and an unknown name are refused", unresolved == ["robin", "alice", "nobody"])
check("an email address is not a mention", J.resolve_mentions("mail evan@tvunetworks.com")[0] == {})

# two registers: the short part is paragraphs, everything after `---` is one collapsed block
adf = J.text_to_adf("@erin verified on prod-8; closing.\n--- Technical detail\ncommit 00be2c36\nbuild 166", {"erin": ("acc-erin", "Erin Zhang")}, detail=True)
top = adf["content"]
check("one paragraph before the rule", top[0]["type"] == "paragraph" and len(top) == 2)
check("the mention is a node with the account id", top[0]["content"][0] == {"type": "mention", "attrs": {"id": "acc-erin", "text": "@Erin Zhang"}})
check("the text after the mention is kept", top[0]["content"][1]["text"] == " verified on prod-8; closing.")
check("the technical part is an expand block with its title", top[1]["type"] == "expand" and top[1]["attrs"]["title"] == "Technical detail" and len(top[1]["content"]) == 2)
check("rendered text reads the mention by display name", "@Erin Zhang verified" in J.body_text(adf))
plain = J.text_to_adf("line one\n---\nline two")
check("without detail=True a dash line is plain text (descriptions keep their rules)", all(n["type"] == "paragraph" for n in plain["content"]) and len(plain["content"]) == 3)
check("an unresolved @name stays text", J.text_to_adf("@nobody hi", {}, detail=True)["content"][0]["content"][0]["type"] == "text")

# a comment in the Markdown subset: bold, bullets and code render above and inside the fold; mentions survive the marks
doc = J.comment_to_adf("**Verdict: PASS** on prod-3, @erin please confirm\n- T1 `16:00 -> 17:00` ok\n--- Test report\n1. Method\n2. Build ancestry", {"erin": ("acc-erin", "Erin Zhang")})
top = doc["content"]
check("bold renders as a mark", top[0]["type"] == "paragraph" and top[0]["content"][0].get("marks") == [{"type": "strong"}])
check("the mention follows the bold text in the same paragraph", any(n["type"] == "mention" and n["attrs"]["id"] == "acc-erin" for n in top[0]["content"]))
check("a bullet list renders before the fold", top[1]["type"] == "bulletList")
check("the fold is a titled expand holding a numbered list", top[2]["type"] == "expand" and top[2]["attrs"]["title"] == "Test report" and top[2]["content"][0]["type"] == "orderedList")
check("rendered text keeps the words for the duplicate check", "Verdict: PASS" in J.body_text(doc) and "@Erin Zhang" in J.body_text(doc))

print("jira close: all offline checks passed" if not failures else f"jira close: {len(failures)} check(s) failed")
sys.exit(1 if failures else 0)
