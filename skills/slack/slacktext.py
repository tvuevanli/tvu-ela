"""Text a person reads in Slack: a Jira key as its link, a title cut at a word, a URL behind a label. A module, not a
capability: every sender that writes a message for Slack builds its pieces here, so each message meets one bar.

The bar (the owner's ruling of 2026-11-26, that every message ela, the runner or Helm sends must read as written for
a person): a Jira key is the link and no bare URL stands beside it; any other URL sits behind a short label; a title is
whole, or cut at a word boundary and closed with "…", never mid-word. Slack's mrkdwn rules themselves live in
slack.py's `mrkdwn_check`, which also flags a bare browse URL beside its own key.
"""
import re

KEY = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
BROWSE = re.compile(r"<?(https?://[^\s<>|]+/browse/([A-Z][A-Z0-9]+-\d+))>?")
LABELLED = re.compile(r"<[^>|]*\|[^>]*>|<[@#!][^>]*>")      # a link with its label, a mention: not bare


def esc(text):
    """Text safe inside a Slack message: &, < and > are Slack's control characters and are written as entities."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(url, label):
    """<url|label>, the label escaped and kept on one line; the bare label when there is no URL."""
    label = " ".join(esc(label).split()).replace("|", "/")
    return f"<{url}|{label}>" if url else label


def key_link(key, base):
    """A Jira key as its own link, `<base/browse/KEY|KEY>`; the bare key when the site names no Jira base."""
    return link(f"{base.rstrip('/')}/browse/{key}", key) if base else key


def cut(text, n):
    """The text on one line, whole when it fits in n characters, otherwise cut at the last space that leaves room for
    "…" and closed with it. A run with no space in reach (CJK text, a long token) is cut at a character, which is a
    word boundary for CJK."""
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    head = t[:n - 1]
    if t[n - 1] != " " and " " in head and len(head.rsplit(" ", 1)[0]) >= n // 2:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ,;:-·") + "…"


def _bare(line):
    plain = LABELLED.sub(lambda m: " " * len(m.group(0)), line)
    for m in BROWSE.finditer(plain):
        rest = line[:m.start()] + " " * (m.end() - m.start()) + line[m.end():]     # the key as a link's label counts
        if re.search(r"(?<![\w/-])" + re.escape(m.group(2)) + r"\b", rest):
            yield m


def bare_browse(line):
    """The bare Jira browse URLs on a line whose key is also written on that line: [(url, key)]. Bare is a URL Slack
    shows as itself, plain or in <…> without a label; a <url|label> link is not bare."""
    return [(m.group(1), m.group(2)) for m in _bare(line)]


def fold_browse(line):
    """The line with each bare browse URL beside its own key folded into that key: the URL is dropped and the first
    bare mention of the key becomes <url|KEY> (when the key is already a link, the URL is only dropped)."""
    while True:
        m = next(_bare(line), None)
        if not m:
            return line
        start = m.start()
        while start and line[start - 1] in " \t":
            start -= 1
        line = line[:start] + line[m.end():]
        plain = LABELLED.sub(lambda x: "\x00" * len(x.group(0)), line)
        k = re.search(r"(?<![\w/-])" + re.escape(m.group(2)) + r"\b", plain)
        if k:
            line = line[:k.start()] + f"<{m.group(1)}|{m.group(2)}>" + line[k.end():]
