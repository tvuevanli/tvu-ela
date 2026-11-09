#!/usr/bin/env python3
"""Credentials embedded in printable text, cut out in place as `<redacted>`. Stdlib only, no imports of its own, so
any read sense can import it beside the scripts that already import a sibling.

  scrub(text)        the text with each embedded credential replaced; a non-string passes through
  guard_output()     wrap sys.stdout and sys.stderr so every write of the calling script is scrubbed

What is cut: a value under a credential-named parameter in a query, a fragment or matrix parameters (key, api-key,
x-api-key, token, secret, password, sig, signature, access_key, passphrase, stream key, x-amz-*); a value under such a
name in a JSON, YAML, header or properties pair (a bare `key` or `auth` excepted there: `"key": "MH-1"` is a ticket);
user:pass@ in a URL; a Bearer or Basic token; an AppSync key; and the shapes of config-server-backend's
util/ApiKeyDetector.java:78-172 (JWT, AWS access key ids, provider keys), anchors relaxed the way its unanchor()
relaxes them. Not cut, because no shape names it: a stream key carried as a bare path segment (rtmp://host/app/KEY).
"""
import re, sys

_B = "[A-Za-z0-9_-]"
_DETECTOR = [
    r"sk-proj-[A-Za-z0-9_-]{48,180}", r"sk-svcacct-[A-Za-z0-9_-]{48,180}", r"sk-admin-[A-Za-z0-9_-]{32,}",
    r"sk-ant-api03-[A-Za-z0-9_-]{90,110}", r"sk-ant-oat01-[A-Za-z0-9_-]{32,}", r"AIzaSy[A-Za-z0-9_-]{33}",
    r"GOCSPX-[A-Za-z0-9_-]{28,}", r"gsk_[A-Za-z0-9]{48,64}", r"pplx-[A-Za-z0-9]{48,}", r"xai-[A-Za-z0-9]{32,}",
    r"sk-or-v1-[A-Za-z0-9]{64}", r"sk-cp-[A-Za-z0-9_-]{32,}", r"fw_[A-Za-z0-9]{32,}", r"tgp_v1_[A-Za-z0-9_-]{32,}",
    r"hf_[A-Za-z0-9]{30,50}", r"r8_[A-Za-z0-9]{36,45}", r"[a-f0-9]{32}\.[A-Za-z0-9]{16,}", r"sk-sp-[A-Za-z0-9]{32,}",
    r"LTAI[A-Za-z0-9]{12,20}", r"sk-[a-f0-9]{32}", r"co_[A-Za-z0-9]{40}", r"(?:mistr_|mistral_)[A-Za-z0-9]{32,}",
    r"(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}", r"ATATT[A-Za-z0-9_-]{100,}=[A-F0-9]{8}",
    r"gh[posu]_[A-Za-z0-9]{36,}", r"github_pat_[A-Za-z0-9_]{22,}", r"glpat-[A-Za-z0-9_-]{20,300}(?:\.[0-9a-z]{9})?",
    r"gl(?:pt|rt|dt)-[A-Za-z0-9._-]{20,}", r"dckr_[po]at_[A-Za-z0-9_-]{27,32}", r"sq(?:u|p|a|co)_[A-Za-z0-9]{40}",
    r"npm_[A-Za-z0-9]{36}", r"xox[bpe][.-][0-9A-Za-z_.-]{10,200}", r"xapp-[0-9]+-[A-Za-z0-9]+-[0-9]+-[A-Za-z0-9]+",
    r"sntry[suo]_[A-Za-z0-9_-]{40,}", r"figd_[A-Za-z0-9_-]{40,}", r"cc(?:l|iprj)_[A-Za-z0-9_]{40}",
    r"[sr]k_(?:live|test)_[A-Za-z0-9]{24,}", r"pk_(?:live|test)_[A-Za-z0-9]{24,}",
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", r"sk-[A-Za-z0-9]{32,64}",
]

RED = "<redacted>"
# the names a credential sits under; `key` and `auth` only where a query parameter makes the meaning plain
_NAMES = (r"(?:x[-_]?)?api[-_]?key|[a-z0-9_-]*token|[a-z0-9_-]*secret|password|passwd|pwd|passphrase|sig|signature"
          r"|access[-_]?key(?:[-_]?id)?|secret[-_]?key|stream[-_]?key|x-amz-(?:signature|credential|security-token)"
          r"|authorization|client[-_]?secret")
_QUERY_NAMES = _NAMES + r"|key|auth"
_SCRUB = [
    # ?key=… &x-api-key=… #access_token=… ;sig=…  (query, fragment, matrix parameters)
    (re.compile(rf"([?&#;](?:{_QUERY_NAMES})=)(?!{RED})[^&#;\s\"'<>]+", re.I), r"\1" + RED),
    # "x-api-key": "…"  'token'='…'  apiKey: …  (JSON, YAML, header maps, properties)
    (re.compile(rf"([\"']?(?<![A-Za-z0-9])(?:{_NAMES})[\"']?\s*[:=]\s*[\"']?)(?!{RED})(?!Bearer\b|Basic\b)"
                r"[^\s\"',;&}<>]{3,}", re.I), r"\1" + RED),
    # scheme://user:pass@host
    (re.compile(r"([a-z][a-z0-9+.-]*://)[^\s:\"',;{}/?#@<>]+:[^\s@\"',;{}/?#<>]+@", re.I), r"\1" + RED + "@"),
    # Authorization: Bearer … / Basic …
    (re.compile(rf"\b(Bearer|Basic)\s+(?!{RED})[A-Za-z0-9._~+/=-]{{8,}}", re.I), r"\1 " + RED),
    # AWS AppSync API key
    (re.compile(r"(?<![A-Za-z0-9_-])da2-[a-z0-9]{26}(?![A-Za-z0-9_-])"), RED),
] + [(re.compile(f"(?<!{_B}){p}(?!{_B})"), RED) for p in _DETECTOR]


def scrub(value):
    """The value with each embedded credential replaced by `<redacted>`; non-strings pass through unchanged."""
    if not isinstance(value, str):
        return value
    for rx, rep in _SCRUB:
        value = rx.sub(rep, value)
    return value


class _Scrubbed:
    """A text stream whose every write is scrubbed; everything else is the wrapped stream's."""
    def __init__(self, stream):
        self._s = stream

    def write(self, text):
        return self._s.write(scrub(text))

    def writelines(self, lines):
        for t in lines:
            self.write(t)

    def __getattr__(self, name):
        return getattr(self._s, name)


def guard_output():
    """Scrub every later write to stdout and stderr of this process; idempotent."""
    for name in ("stdout", "stderr"):
        cur = getattr(sys, name)
        if not isinstance(cur, _Scrubbed):
            setattr(sys, name, _Scrubbed(cur))
