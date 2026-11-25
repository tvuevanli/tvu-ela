#!/usr/bin/env bash
# ela UserPromptSubmit hook — the language tag `#zh` in the owner's message switches the session to Chinese.
# Reads the prompt (JSON: prompt) on stdin. A standalone `#zh`, any case, outside a URL, a code span, a quote or
# a path, adds context telling the session to answer in Chinese from this message to the end of the conversation.
# A tag that is quoted ('#zh', "#zh", `#zh`) is a mention of the tag, not the tag; a desk brief to a worker (it opens
# with "desk brief", or carries the worktree note `ela session open` appends) is the desk's text, not the owner's
# message, so a tag in it is a mention too. Reason: a worker brief about this hook quoted '#zh' and switched the
# worker to Chinese (2026-11-25).
# No tag: no output. Always exit 0: this hook never blocks a prompt.
# One tag only, by the owner's word (2026-11-24): bare `zh`, `chn`, `cn` and `中文` misfired on ordinary text;
# `zhn` replaced them, then `#zh` replaced `zhn` (his word, the same day), the `#` keeping it off ordinary text.
# The standing rule — English by default, Chinese on request — is the working preferences' first line.
INPUT="$(cat)"
python3 - "$INPUT" <<'PY' 2>/dev/null
import json, re, sys
try:
    prompt = json.loads(sys.argv[1]).get("prompt") or ""
except Exception:
    sys.exit(0)
if re.match(r"\s*desk brief\b", prompt, re.I) or "the desk lands it with `ela session land" in prompt:
    sys.exit(0)                                                    # a desk brief: the desk speaks, not the owner
text = re.sub(r"```.*?(```|$)", " ", prompt, flags=re.S)          # fenced code
text = re.sub(r"`[^`\n]*`", " ", text)                             # code spans
text = re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", " ", text, flags=re.I) # URLs
text = re.sub(r"\S*[/\\]\S*", " ", text)                           # paths: any token with a slash
text = re.sub(r'"[^"\n]*"|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』', " ", text) # double-quoted spans
WORD = r"A-Za-z0-9_.\-㐀-鿿'‘’`"                            # a tag touching these is part of a word or a quote
tag = re.compile(rf"(?<![{WORD}#])#zh(?![{WORD}])|(?<![{WORD}#])#zh(?=\.(?:\s|$))", re.I)
if not tag.search(text):
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": (
        "ela: the owner tagged this message `#zh`: answer in Chinese from this message to the end of the "
        "conversation, untagged messages included, until he asks for English. Domain terms (graph, tangible, "
        "bundle, lane, profile, build, Fixed In) stay English. Durable outputs (Jira, repos, the knowledge "
        "base, Slack drafts for colleagues) keep their own language rules."),
}}, ensure_ascii=False))
PY
exit 0
