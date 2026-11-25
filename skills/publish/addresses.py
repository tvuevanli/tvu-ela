"""What counts as an IPv4 address in text a colleague reads: one rule for the publish redaction
(publish.redact) and the commit-time content guard (hooks/content-guard.sh). Stdlib only, no I/O.

A dotted quad is an address when its four numbers are each at most 255, it is not loopback, the
unspecified address or a mask, and nothing marks it as a version number. A host after `://` is always
an address, whatever else the line says (`/v1/` in a URL path is not a version)."""
import re

IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
PRIVATE = re.compile(r"^(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)")
VERSION_LINE = re.compile(r"(?i)version|build|image|tag|release|\bv\d")
NOT_HOSTS = ("127.", "0.0.0.0", "255.")


def version_context(text, start, end, quad):
    """A four-part number whose own neighbours say it is a version: a `+build` suffix (`a.b.c.d+198`,
    `objectd@a.b.c.d+117`), a `v` prefix, or one side of a version change written with an arrow
    (`a.b.c.d → a.b.c.d`) when it is not in a private range; an address change stays an address."""
    if re.match(r"\+\d", text[end:end + 2]) or re.search(r"(?i)(?<![a-z])v$", text[max(0, start - 2):start]):
        return True
    near = text[max(0, start - 4):start] + "|" + text[end:end + 4]
    return bool(re.search(r"→|->", near)) and not PRIVATE.match(quad)


def is_address(text, m):
    """`m`, an IPV4 match in `text`: an address, or a number that only looks like one (a version on a line
    that names versions, or one marked by its neighbours)."""
    quad = m.group(0)
    if any(int(o) > 255 for o in quad.split(".")) or quad.startswith(NOT_HOSTS):
        return False
    if text[max(0, m.start() - 3):m.start()] == "://":
        return True
    if version_context(text, m.start(), m.end(), quad):
        return False
    line_start = text.rfind("\n", 0, m.start()) + 1
    line_end = text.find("\n", m.end())
    return not VERSION_LINE.search(text[line_start:line_end if line_end != -1 else len(text)])


def addresses(text):
    """The address matches in `text`, in order."""
    return [m for m in IPV4.finditer(text) if is_address(text, m)]


# A company host name is an address as much as a dotted quad: a subdomain of the company's domains names one machine
# or one internal service. The bare domain (the company's site) and the public pages listed here are not internal.
INTERNAL_HOST = re.compile(r"(?<![\w.@-])(?:[a-z0-9-]+\.)+tvunetworks\.(?:com|cn|net)(?::\d{2,5})?(?![\w-])", re.I)
PUBLIC_HOSTS = ("www.", "document.")


def internal_hosts(text):
    """The company host names in `text` that are not public pages, in order (an email's domain is not a host here:
    the email rule refuses the whole address)."""
    return [m for m in INTERNAL_HOST.finditer(text) if not m.group(0).lower().startswith(PUBLIC_HOSTS)]
