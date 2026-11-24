#!/usr/bin/env python3
"""The description standard, offline: the sections each issue type requires, headings in both forms, the fold
ignored, and the English-first warning."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "jira"))
import jira as J  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

bug = "### Problem\nIt fails.\n### Steps to reproduce\n1. do\n### QA verification\n1. check"
check("a bug in the accepted shape passes", J.description_standard("Bug", bug) == ([], []))
check("a bug may say Done when", J.description_standard("Bug", bug.replace("QA verification", "Done when"))[0] == [])
check("a bug without steps is missing them", J.description_standard("Bug", "### Problem\nx\n### Done when\ny")[0] == ["Steps to reproduce"])
task = "**Goal**\nwhy\n**Scope**\nwhat\n**Done when**\n- a"
check("bold labels count as headings", J.description_standard("Task", task) == ([], []))
check("an epic uses the task shape", J.description_standard("Epic", task)[0] == [])
check("a sub-task needs scope and a criterion", J.description_standard("Sub-task", "### Scope\nx")[0] == ["Done when or QA verification"])
check("empty text misses everything", len(J.description_standard("Task", "")[0]) == 3)
folded = "### Goal\nx\n### Scope\ny\n--- Technical detail\n### Done when\nz"
check("a heading under the fold does not count", J.description_standard("Task", folded)[0] == ["Done when or QA verification"])
_, w = J.description_standard("Task", "### 目标\n中文\n### Goal\nx")
check("Chinese first is warned", len(w) == 1)
_, w = J.description_standard("Task", task + "\n### 中文\n内容")
check("English first, Chinese after, no warning", w == [])
# the gate refuses the same way in a dry run as under --apply: same exit code, same reason
import argparse, contextlib, io
def gate(apply, nonstandard=None, description="### Goal\nx"):
    a = argparse.Namespace(apply=apply, nonstandard=nonstandard, description=description)
    err, code = io.StringIO(), None
    with contextlib.redirect_stderr(err):
        try:
            J._standard_gate(a, "Task", {})
        except SystemExit as e:
            code = e.code
    return code, err.getvalue()
dry, live = gate(False), gate(True)
check("a dry run refuses a nonstandard create", dry[0] == 2 and "refused:" in dry[1])
check("the dry run's refusal is --apply's, word for word", dry == live)
check("--nonstandard passes the dry run", gate(False, "tracking ticket")[0] is None)
check("a standard description passes the dry run", gate(False, description=task)[0] is None)
sys.exit(1 if failures else 0)
