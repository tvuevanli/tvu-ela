#!/usr/bin/env bash
# ela UserPromptSubmit hook — a language tag in the owner's message switches that one reply to Chinese.
# Reads the prompt (JSON: prompt) on stdin. A standalone tag `zh`, `chn`, `cn` or `中文`, any case, outside
# a URL, a code span or a path, adds context telling the session to answer this message in Chinese.
# No tag: no output. Always exit 0: this hook never blocks a prompt.
# `zh` is the canonical code (ISO 639-1); `chn` is accepted because the owner types it.
# The standing rule — English by default, Chinese on request — is the working preferences' first line.
INPUT="$(cat)"
python3 - "$INPUT" <<'PY' 2>/dev/null
import json, re, sys
try:
    prompt = json.loads(sys.argv[1]).get("prompt") or ""
except Exception:
    sys.exit(0)
text = re.sub(r"```.*?(```|$)", " ", prompt, flags=re.S)          # fenced code
text = re.sub(r"`[^`\n]*`", " ", text)                             # code spans
text = re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", " ", text, flags=re.I) # URLs
text = re.sub(r"\S*[/\\]\S*", " ", text)                           # paths: any token with a slash
WORD = r"A-Za-z0-9_.\-㐀-鿿"                                # a tag touching these is part of a word
tag = re.compile(rf"(?<![{WORD}])(?:zh|chn|cn|中文)(?![{WORD}])|(?<![{WORD}])(?:zh|chn|cn)(?=\.(?:\s|$))", re.I)
if not tag.search(text):
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": (
        "ela: the owner tagged this message for Chinese. Answer this one message in Chinese; domain terms "
        "(graph, tangible, bundle, lane, profile, build, Fixed In) stay English. The tag covers this reply "
        "only; durable outputs (Jira, repos, the knowledge base, Slack drafts for colleagues) keep their own "
        "language rules."),
}}, ensure_ascii=False))
PY
exit 0
