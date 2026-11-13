#!/usr/bin/env python3
"""Slack's mrkdwn against Markdown, offline: `slack.py check` names every construct Slack prints literally (a heading,
double asterisks, a Markdown link, a pipe table, a rule, a nested list item, a language tag on a fence, a marker
touching CJK text), leaves code alone, and --fix makes each mechanical repair. No token is read and nothing is called."""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "slack"))
import slack as S  # noqa: E402

failures = []
def check(name, cond, got=None):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)
        if got is not None:
            print("     ", got)

rules = lambda t: [x["rule"] for x in S.mrkdwn_check(t)]
GOOD = ("*Build 92* is on QA, _not yet verified_, ~build 91~.\n• `ur-caller` 2.1.92\n• <https://x.example/a|the mail>\n"
        "> quoted line\n```\n# not a heading\n**kept**  | a | b |\n```\n中文 *加粗* 和 _斜体_。")
check("what Slack renders passes: bold, italic, strike, code, a bare fence, a quote, a link, the bullet", rules(GOOD) == [], rules(GOOD))
check("a heading", rules("# Title\ntext") == ["heading"])
check("double asterisks", rules("this is **bold** here") == ["double-asterisk"])
check("a Markdown link", rules("see [the page](https://x.example/p)") == ["md-link"])
check("a pipe table, which has no mechanical repair", [(x["rule"], x["fixable"]) for x in S.mrkdwn_check("| a | b |\n|---|---|\n| 1 | 2 |")] == [("table", False)] * 3)
check("a rule", rules("above\n---\nbelow") == ["rule"])
check("a nested list item", rules("• one\n  • under one\n    - deeper") == ["nested-list", "nested-list"])
check("a language tag on a fence", rules("```python\nprint(1)\n```") == ["fence-language"])
check("text on the fence line that is not a tag alone is the block's content", rules("```claude plugin install x\nmore```") == [])
check("a marker touching CJK text", rules("这是*重点*内容") == ["cjk-boundary"] and rules("结论_未验证_。") == ["cjk-boundary"] and rules("旧的~作废~了") == ["cjk-boundary"])
check("CJK punctuation is a boundary; so is a space", rules("结论：*通过*。") == [] and rules("这是 *重点* 内容") == [])
check("an underscore inside a name is not a marker", rules("set preferred_pool_id on the node, 用 a_b_c 的值") == [])
check("the line of each slip is its line in the text, past a code block", [(x["rule"], x["line"]) for x in S.mrkdwn_check("ok\n```\na\nb\n```\n# late")] == [("heading", 6)])
BAD = "# Result\nsee [mail](https://x.example/m), **passed**\n---\n• one\n  - under\n```json\n{\"a\": 1}\n```\n这是*重点*内容"
FIXED = "*Result*\nsee <https://x.example/m|mail>, *passed*\n• one\n• under\n```\n{\"a\": 1}\n```\n这是 *重点* 内容"
check("--fix: each mechanical repair, code untouched", S.mrkdwn_fix(BAD) == FIXED and rules(FIXED) == [], S.mrkdwn_fix(BAD))
check("a repair of clean text changes nothing", S.mrkdwn_fix(GOOD) == GOOD)
LIST = "Next:\n- first *thing*\n  - under first\n    1. deeper, with `- code`\n- second\n* star\n+ plus\n```\n- in a block\n```\n-not a bullet\n- \n*bold* line"
check("--fix: a - item line takes the • bullet; nested items flatten where they stood, text whole; code and bold untouched",
      S.mrkdwn_fix(LIST) == "Next:\n• first *thing*\n• under first\n• deeper, with `- code`\n• second\n• star\n• plus\n```\n- in a block\n```\n-not a bullet\n- \n*bold* line", S.mrkdwn_fix(LIST))
check("a - item line is no slip: it holds no post", rules("Next:\n- first\n- second") == [] and S.mrkdwn_slips("- only") == [])
check("the repaired list is clean and repairing it again changes nothing", rules(S.mrkdwn_fix(LIST)) == [] and S.mrkdwn_fix(S.mrkdwn_fix(LIST)) == S.mrkdwn_fix(LIST))
check("post's dry-run flags come from the same check", len(S.mrkdwn_slips(BAD)) == 7 and S.mrkdwn_slips(GOOD) == [])

def run(*args, stdin=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_") and k != "ELA_ENV_FILE"}
    p = subprocess.run([sys.executable, os.path.join(ROOT, "skills", "slack", "slack.py"), "check", *args], input=stdin, capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr
rc, out, err = run("--text", GOOD)
check("the verb: clean text exits 0 with no token", rc == 0 and not out and not err, (rc, out, err))
rc, out, err = run("--file", "-", stdin=BAD)
check("slips exit 1, each named with its line", rc == 1 and "line 1: heading" in err and "line 9: cjk-boundary" in err, (rc, err))
rc, out, err = run("--file", "-", "--fix", stdin=BAD)
check("--fix prints the repaired text and exits 0 when nothing is left", rc == 0 and out == FIXED and not err, (rc, out, err))
rc, out, err = run("--text", "**a**\n| x | y |", "--fix")
check("--fix exits 1 when a table remains, the rest repaired", rc == 1 and out == "*a*\n| x | y |" and "table" in err, (rc, out, err))
rc, out, err = run("--text", BAD, "--fix", "--json")
d = json.loads(out)
check("--json: slips with rule, line, why, fixable; fixed and what is left", rc == 0 and d["clean"] is False and d["fixed"] == FIXED and d["left"] == []
      and set(d["slips"][0]) == {"rule", "line", "why", "fixable"})
check("neither or both of --text and --file is a usage error", run()[0] == 2 and run("--text", "a", "--file", "-", stdin="a")[0] == 2)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
