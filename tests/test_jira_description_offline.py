#!/usr/bin/env python3
"""A ticket description's Markdown subset, offline: headings, both list kinds, the marks and links, the `---` fold, and a
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

# links: [text](url) links its text; a bare URL links itself; code is never linkified
def marked(line):
    return [(n["text"], n.get("marks", [])) for n in J.markdown_to_adf(line)["content"][0]["content"]]
LINK = lambda href: {"type": "link", "attrs": {"href": href}}
check("[text](url) is a link on its text", marked("See [the spec](https://wiki.example/x?a=1) now") == [
    ("See ", []), ("the spec", [LINK("https://wiki.example/x?a=1")]), (" now", [])])
check("a bare URL links itself", marked("Log: https://logs.example/t/42 here") == [
    ("Log: ", []), ("https://logs.example/t/42", [LINK("https://logs.example/t/42")]), (" here", [])])
check("trailing punctuation stays outside the link", marked("see http://a.example/p.") == [
    ("see ", []), ("http://a.example/p", [LINK("http://a.example/p")]), (".", [])])
check("a closing parenthesis the URL did not open stays outside", marked("(https://a.example/x)") == [
    ("(", []), ("https://a.example/x", [LINK("https://a.example/x")]), (")", [])])
check("a balanced parenthesis stays in the URL", marked("https://w.example/A_(b)")[0][0] == "https://w.example/A_(b)")
check("a URL inside code is not linkified", marked("run `curl https://a.example/x` first") == [
    ("run ", []), ("curl https://a.example/x", [{"type": "code"}]), (" first", [])])
check("a URL inside bold is bold and linked", marked("**at https://a.example**") == [
    ("at ", [{"type": "strong"}]), ("https://a.example", [{"type": "strong"}, LINK("https://a.example")])])
check("a [text](url) target is not linked twice", len(marked("[x](https://a.example/y)")) == 1)
check("links in list items and headings",
      J.markdown_to_adf("- https://a.example")["content"][0]["content"][0]["content"][0]["content"][0]["marks"] == [LINK("https://a.example")]
      and J.markdown_to_adf("## [Spec](https://a.example)")["content"][0]["content"][0]["marks"] == [LINK("https://a.example")])
check("a bare scheme is not a link", marked("http:// alone") == [("http:// alone", [])])
check("body_text keeps a link's target", "https://a.example/y" in J.body_text(J.markdown_to_adf("[x](https://a.example/y)")))
check("a comment keeps link marks next to a mention",
      [n.get("marks") for n in J.comment_to_adf("@ann see https://a.example", {"ann": ("id1", "Ann")})["content"][0]["content"]]
      == [None, None, [LINK("https://a.example")]])

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
