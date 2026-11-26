#!/usr/bin/env python3
"""lang-tag: a standalone `#zh` tag adds Chinese-for-the-session context, a standalone `#send` adds the send-approved
context, both join in one output; anything else passes silently, never blocks."""
import json, os, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "lang-tag.sh")
fail = 0


def run(raw):
    p = subprocess.run(["bash", HOOK], input=raw, capture_output=True, text=True)
    return p.returncode, p.stdout


def tags(prompt):
    """The tags the hook reported for this prompt, as a set, or None on a bad exit or a malformed output."""
    rc, out = run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}))
    if rc != 0:
        return None
    if not out.strip():
        return set()
    try:
        assert len(out.strip().splitlines()) == 1                  # one hookSpecificOutput, never two
        ctx = json.loads(out)["hookSpecificOutput"]
        assert ctx["hookEventName"] == "UserPromptSubmit"
        text = ctx["additionalContext"]
    except Exception:
        return None
    got = set()
    if "answer in Chinese" in text and "end of the conversation" in text:
        got.add("zh")
    if "tagged this message `#send`" in text and "without a preview" in text and "this message only" in text:
        got.add("send")
    return got if got else None


def check(prompt, want):
    global fail
    want = {"zh"} if want is True else set() if want is False else set(want)
    ok = tags(prompt) == want
    print(("ok   " if ok else "FAIL ") + f"{','.join(sorted(want)) or 'none'}: {prompt!r}")
    fail |= not ok


for p in ["#zh what is on prod-3", "#zh: explain MH-3555", "explain MH-3555 (#zh)", "#ZH why did it fail",
          "why did it fail? #Zh", "#zh 这个 graph 跑在哪", "what changed? #zh.", "#ZH\nfirst line is the tag",
          'the reply "ok" is fine #zh', "#zh — the 'lang-tag' hook is fine", "#zh the brief mentioned desk briefs"]:
    check(p, True)
for p in ["explain MH-3555", "zhn what is on prod-3", "zh: explain MH-3555", "chn what is on prod-3", "CN why did it fail",
          "中文 这个 graph 跑在哪", "the zhang branch", "#zhn is not a tag", "##zh is not a tag", "issue#zh is not a tag",
          "open https://example.cn/#zh", "run `ela brief --tag #zh`", "see docs/#zh/manual.md",
          "```\nlocale = #zh\n```\nwhat does this do", "the #zh-CN locale string", "mail.#zh is a host", "",
          # a quoted or backticked tag is a mention of the tag, not the tag
          "the hook fired on '#zh' in a sentence", 'the hook fired on "#zh" in a sentence', "the hook fired on `#zh`",
          "the hook fired on ‘#zh’", "the hook fired on “#zh”", "the hook fired on 「#zh」", 'the "#zh tag" form',
          "an unclosed `#zh mention",
          # a desk brief to a worker is the desk's text, not the owner's message
          "desk brief (2026-11-25): the hook fired on #zh in a brief", "Desk brief: fix #zh handling",
          "fix the hook on #zh. You work in the worktree W on branch B, never in the shared checkout C; commit here, "
          "and the desk lands it with `ela session land N`."]:
    check(p, False)

# `#send`: same detection rules as `#zh`, alone or beside it, one output carrying both
for p in ["#send reply to the thread that it is fixed", "tell the QA lead it is on daily #send", "#SEND post it",
          "reply in the thread (#send)", "post the summary #send."]:
    check(p, {"send"})
for p in ["#zh #send reply to the thread", "#send 回复这个 thread #zh", "#ZH tell the QA lead #Send"]:
    check(p, {"zh", "send"})
for p in ["the hook fired on '#send' in a sentence", 'the hook fired on "#send"', "the hook fired on `#send`",
          "open https://example.com/page#send", "see https://tvunetworks.slack.com/archives/C1/p2#send now",
          "the #sender field", "##send is not a tag", "issue#send is not a tag", "see docs/#send/manual.md",
          "desk brief (2026-11-26): add #send to the hook", "Desk brief: #send handling",
          "add #send. You work in the worktree W on branch B, never in the shared checkout C; commit here, "
          "and the desk lands it with `ela session land N`."]:
    check(p, set())
check("'#send' is quoted, the real tag is #zh", {"zh"})
check("open https://example.com/#zh and #send it", {"send"})

for raw in ["not json", "{}", json.dumps({"prompt": None})]:
    rc, out = run(raw)
    ok = rc == 0 and not out.strip()
    print(("ok   " if ok else "FAIL ") + f"malformed input passes: {raw!r}")
    fail |= not ok

raise SystemExit(fail)
