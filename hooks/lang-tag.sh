#!/usr/bin/env bash
# ela UserPromptSubmit hook — the owner's message tags: `#zh` switches the session to Chinese, `#send` approves in
# advance the Slack message(s) answering that one message.
# Reads the prompt (JSON: prompt) on stdin. A standalone `#zh`, any case, outside a URL, a code span, a quote or
# a path, adds context telling the session to answer in Chinese from this message to the end of the conversation.
# A standalone `#send`, under the same rules, adds context telling the session to send the answering post as ela
# without a preview, except where it would go under his name, reach a target or mention he did not name, commit to a
# date, owner or release scope, or rest on an uncertain fact. Reason: some posts he does not want to review, and a tag
# on the message is his word for that one message, not a standing rule (elak blueprint/working-with-evan.md, the
# `#send` tag, 2026-11-26). Both tags may appear; one hookSpecificOutput carries both contexts, joined.
# A tag that is quoted ('#zh', "#zh", `#zh`) is a mention of the tag, not the tag; a desk brief to a worker (it opens
# with "desk brief", or carries the worktree note `ela session open` appends) is the desk's text, not the owner's
# message, so a tag in it is a mention too. Reason: a worker brief about this hook quoted '#zh' and switched the
# worker to Chinese (2026-11-25). A cross-session message (it carries a `<cross-session-message` element, or opens
# with "Another Claude session sent a message") is a peer session's text, so it gets no tag context either. Reason: a
# worker's report naming `#zh` and `#send` switched the desk to Chinese and approved a Slack send (2026-11-26).
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
if "<cross-session-message" in prompt or re.match(r"\s*Another Claude session sent a message", prompt, re.I):
    sys.exit(0)                                                    # a peer session's message, not the owner's
text = re.sub(r"```.*?(```|$)", " ", prompt, flags=re.S)          # fenced code
text = re.sub(r"`[^`\n]*`", " ", text)                             # code spans
text = re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", " ", text, flags=re.I) # URLs
text = re.sub(r"\S*[/\\]\S*", " ", text)                           # paths: any token with a slash
text = re.sub(r'"[^"\n]*"|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』', " ", text) # double-quoted spans
WORD = r"A-Za-z0-9_.\-㐀-鿿'‘’`"                            # a tag touching these is part of a word or a quote
def tagged(name):
    return re.search(rf"(?<![{WORD}#])#{name}(?![{WORD}])|(?<![{WORD}#])#{name}(?=\.(?:\s|$))", text, re.I)
ctx = []
if tagged("zh"):
    ctx.append(
        "ela: the owner tagged this message `#zh`: answer in Chinese from this message to the end of the "
        "conversation, untagged messages included, until he asks for English. Domain terms (graph, tangible, "
        "bundle, lane, profile, build, Fixed In) stay English. Durable outputs (Jira, repos, the knowledge "
        "base, Slack drafts for colleagues) keep their own language rules.")
if tagged("send"):
    ctx.append(
        "ela: the owner tagged this message `#send`: the Slack message(s) answering this one request are approved "
        "in advance. Write the text, run `ela slack check`, and send it as ela with `--apply` to the thread or person "
        "the request names, without a preview; afterwards give the permalink and a one-line summary. Stop for a "
        "preview instead when the post would go under his own name, to a target or mention he did not name, commits "
        "to a date, owner or release scope, or rests on a fact you are not sure of. Applies to this message only "
        "(elak blueprint/working-with-evan.md, the #send tag, 2026-11-26).")
if not ctx:
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "\n\n".join(ctx),
}}, ensure_ascii=False))
PY
exit 0
