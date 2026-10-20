#!/usr/bin/env python3
"""A ticket description's Markdown subset, offline: headings, both list kinds, the two marks, the `---` fold, and a
plain-text description rendered exactly as before."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "jira"))
import jira as J  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

def kinds(adf):
    return [n["type"] for n in adf["content"]]

# plain text: the same ADF text_to_adf gives, so existing callers see no change
plain = "First line.\n\nSecond line, no markup."
check("plain text is unchanged", J.markdown_to_adf(plain) == J.text_to_adf(plain))
check("empty text is one empty paragraph", J.markdown_to_adf("") == J.text_to_adf(""))

# headings
doc = J.markdown_to_adf("# One\n## Two\n### Three")
check("three heading levels", [n["attrs"]["level"] for n in doc["content"]] == [1, 2, 3])
check("heading text has no hashes", doc["content"][0]["content"] == [{"type": "text", "text": "One"}])

# lists: consecutive items share one list; a change of kind or a blank line starts another
doc = J.markdown_to_adf("- a\n* b\n1. one\n2. two\n\n- c")
check("bullets, numbered, bullets", kinds(doc) == ["bulletList", "orderedList", "bulletList"])
check("both bullet markers join one list", len(doc["content"][0]["content"]) == 2)
check("numbered items keep their text", doc["content"][1]["content"][1]["content"][0]["content"][0]["text"] == "two")

# marks
nodes = J.markdown_to_adf("Run **now** in `copier.cpp:42` please")["content"][0]["content"]
check("bold and code marks", [(n["text"], [m["type"] for m in n.get("marks", [])]) for n in nodes] == [
    ("Run ", []), ("now", ["strong"]), (" in ", []), ("copier.cpp:42", ["code"]), (" please", [])])
check("a bold line is not a bullet", kinds(J.markdown_to_adf("**Cause** first")) == ["paragraph"])

# the fold: everything after the first dash line, titled by its words
doc = J.markdown_to_adf("### Problem\nIt breaks.\n--- Call sites\n- a.cs:1\n--- not a second fold")
check("fold is the last block", kinds(doc) == ["heading", "paragraph", "expand"])
check("fold title from the dash line", doc["content"][-1]["attrs"]["title"] == "Call sites")
check("only the first dash line folds", kinds(doc["content"][-1]) == ["bulletList", "paragraph"])
check("bare dash line titles Technical detail",
      J.markdown_to_adf("x\n---\ny")["content"][-1]["attrs"]["title"] == "Technical detail")
check("an empty fold adds nothing", kinds(J.markdown_to_adf("x\n---\n\n")) == ["paragraph"])

print(f"\n{len(failures)} failure(s)" if failures else "\njira description: all checks passed")
sys.exit(1 if failures else 0)
