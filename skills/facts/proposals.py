#!/usr/bin/env python3
"""mediahub-bot's knowledge proposals, read into the fact store for the owner's brief. Stdlib only, read-only.

  proposals.py show [--hours N] [--json]     what the store holds (every proposal, or those first seen in the last N hours)

The bot proposes a product fact its knowledge snapshot lacks and changes nothing itself; each proposal carries the
marker `mhbot-knowledge-proposal v1`, a claim, evidence, a source (a person in the thread, or a read the bot made) and
the thread it came from. It sends them two ways, each off until the bot's access file turns it on:

  channel   one parent message a day in a Slack channel, each proposal a reply under it
            (site.json `knowledge_proposals.channel`, a channel id; read through ela's Slack read and its store)
  files     one JSON file per proposal under <MHBOT_ROOT>/data/knowledge-proposals/, written whole then renamed
            (site.json `knowledge_proposals.dir`, the directory on this machine)

`ela facts refresh` (source `proposals`) reads both into <runtime>/facts/proposals/proposals.json, one record per
claim (the bot's own key: the claim lower-cased, whitespace collapsed, sha256, 16 hex), the routes it came by and the
time ela first saw it. A route left unset is a state, not a gap; a route set and unreadable is a gap, and the other
route is still read. Nothing here writes elak or answers the bot: the owner rules on each proposal in the brief, and
a record reaches elak only on his word (ADR 0001, 0011).

Exit codes: 0 ok · 2 usage.
"""
import argparse, datetime, glob, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
MARK = "mhbot-knowledge-proposal v1"
HORIZON_DAYS = 8                 # the channel's parents re-read each pass: the Slack source's own horizon
KEEP_DAYS = 60                   # a record is dropped this long after ela first saw it
SOURCE_WORDS = {"a person in the thread": "person", "a read the bot made": "read"}
POST_RX = re.compile(r"<(?P<link>https?://[^|>]+)\|[^>]*>.*?\*Claim:\*\s*(?P<claim>.*?)\n\*Evidence:\*\s*(?P<evidence>.*?)"
                     r"\n\*Source:\*\s*(?P<source>.*?)\s*\n`" + re.escape(MARK) + "`", re.S)


def F():
    sys.path.insert(0, HERE)
    import facts  # noqa: E402
    return facts


def key(claim):
    """The bot's own claim key (mhbot/feedback.py `_key`), so a claim sent both ways is one record."""
    return hashlib.sha256(" ".join(str(claim).lower().split()).encode("utf-8")).hexdigest()[:16]


def config(site):
    """(channel id or None, directory or None) from site.json `knowledge_proposals`."""
    c = site.get("knowledge_proposals") or {}
    if not isinstance(c, dict):
        return None, None
    d = c.get("dir")
    return (c.get("channel") or None), (os.path.expanduser(d) if d else None)


def unescape(s):
    """Slack escapes exactly three characters in a message's text."""
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def parse_post(text):
    """One proposal from the bot's reply text, or None when the text is not one."""
    if MARK not in (text or ""):
        return None
    m = POST_RX.search(text)
    if not m:
        return None
    src = unescape(m.group("source")).strip()
    return {"claim": unescape(m.group("claim")).strip(), "evidence": unescape(m.group("evidence")).strip(),
            "source": SOURCE_WORDS.get(src, "unstated"), "thread": m.group("link")}


def parse_file(doc):
    """One proposal from a file the bot wrote, or None when it is not one (no marker, no claim)."""
    if not isinstance(doc, dict) or doc.get("marker") != MARK or not str(doc.get("claim") or "").strip():
        return None
    src = doc.get("source")
    return {"claim": str(doc["claim"]).strip(), "evidence": str(doc.get("evidence") or "").strip(),
            "source": src if src in ("person", "read") else "unstated", "thread": doc.get("thread") or "",
            "written_at": doc.get("written_at") or ""}


def read_dir(path):
    """(proposals, skipped count). Raises OSError when the directory is not there or not readable."""
    if not os.path.isdir(path):
        raise OSError(f"no directory at {path}")
    out, skipped = [], 0
    for f in sorted(glob.glob(os.path.join(path, "*.json"))):    # a .tmp is half a file: never read
        try:
            p = parse_file(json.load(open(f, encoding="utf-8")))
        except (OSError, ValueError):
            p = None
        if p is None:
            skipped += 1
            continue
        p["file"] = os.path.basename(f)
        out.append(p)
    return out, skipped


def read_channel(S, tok, ch, oldest):
    """(proposals, skipped count) from the channel's parents since `oldest` and their replies, through slack.py's
    store-backed reads. Raises S.Transient, or SystemExit from a Slack call that gave up."""
    out, skipped = [], 0
    parents, _ = S.thread_parents(tok, ch, oldest)
    for parent in sorted(parents, key=lambda m: float(m["ts"])):
        msgs = [parent] + (S.replies_rows(tok, ch, parent) if parent.get("reply_count") else [])
        for m in msgs:
            if MARK not in (m.get("text") or ""):
                continue
            p = parse_post(m["text"])
            if p is None:
                skipped += 1
                continue
            p["post"] = S.permalink_of(ch, m["ts"])
            p["posted_at"] = datetime.datetime.fromtimestamp(float(m["ts"])).astimezone().isoformat(timespec="seconds")
            out.append(p)
    return out, skipped


def merge(store, found, route, at):
    """Fold one route's proposals into the store, one record per claim key. → how many keys were new."""
    new = 0
    for p in found:
        k = key(p["claim"])
        rec = store.get(k)
        if rec is None:
            rec = store[k] = {"key": k, "claim": p["claim"], "evidence": p["evidence"], "source": p["source"],
                              "thread": p.get("thread") or "", "routes": [], "seen_at": at}
            new += 1
        if route not in rec["routes"]:
            rec["routes"].append(route)
        for f in ("post", "posted_at", "file", "written_at"):
            if p.get(f) and not rec.get(f):
                rec[f] = p[f]
        for f in ("evidence", "thread"):                  # a later route fills what an earlier one left empty
            if p.get(f) and not rec.get(f):
                rec[f] = p[f]
        if rec["source"] == "unstated" and p["source"] != "unstated":
            rec["source"] = p["source"]
    return new


def refresh(env_file, site, slack=None, now=None):
    """Read both routes into the store. → {"line", "gaps", "state", "new", "count"}; never raises for a route."""
    Fm = F()
    now = now or Fm.now()
    at = now.isoformat(timespec="seconds")
    channel, directory = config(site)
    path = os.path.join(Fm.store_dir("proposals"), "proposals.json")
    store = Fm.read_json(path, {}) or {}
    parts, gaps, new = [], [], 0
    if not channel and not directory:
        return {"line": "proposals: not configured (site.json knowledge_proposals names no channel and no directory)",
                "gaps": [], "state": "not configured", "new": 0, "count": len(store)}
    if channel:
        try:
            if slack is None:
                sys.path.insert(0, os.path.join(SKILLS, "slack"))
                import slack as S  # noqa: E402
            else:
                S = slack
            tok = S.token(env_file)
            oldest = (now - datetime.timedelta(days=HORIZON_DAYS)).timestamp()
            found, skipped = read_channel(S, tok, channel, oldest)
            n = merge(store, found, "channel", at); new += n
            parts.append(f"channel {len(found)} ({n} new{f', {skipped} unparsed' if skipped else ''})")
        except SystemExit as e:
            gaps.append(f"channel {channel}: slack exit {e.code}")
            parts.append("channel gap")
        except Exception as e:  # noqa: BLE001 — one route must not stop the other
            gaps.append(f"channel {channel}: {type(e).__name__}: {str(e)[:160]}")
            parts.append("channel gap")
    else:
        parts.append("channel not configured")
    if directory:
        try:
            found, skipped = read_dir(directory)
            n = merge(store, found, "files", at); new += n
            parts.append(f"files {len(found)} ({n} new{f', {skipped} unparsed' if skipped else ''})")
        except OSError as e:
            gaps.append(f"files: {e}")
            parts.append("files gap")
    else:
        parts.append("files not configured")
    floor = (now - datetime.timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    store = {k: r for k, r in store.items() if str(r.get("seen_at") or "") >= floor}
    Fm.write_json(path, store)
    return {"line": f"proposals: {', '.join(parts)}; {len(store)} held" + (f" — gaps: {'; '.join(gaps)}" if gaps else ""),
            "gaps": gaps, "state": None, "new": new, "count": len(store)}


def rows(hours=None, now=None):
    """The store's records, newest first; with `hours`, only those ela first saw inside that window."""
    Fm = F()
    store = Fm.read_json(os.path.join(Fm.store_dir("proposals"), "proposals.json"), {}) or {}
    out = sorted(store.values(), key=lambda r: str(r.get("seen_at") or ""), reverse=True)
    if hours is not None:
        floor = ((now or Fm.now()) - datetime.timedelta(hours=hours)).isoformat(timespec="seconds")
        out = [r for r in out if str(r.get("seen_at") or "") >= floor]
    return out


def cmd_show(a):
    Fm = F()
    rs, wm = rows(a.hours), Fm.watermark("proposals")
    if a.json:
        print(json.dumps({"read_at": wm.get("at"), "state": wm.get("state"), "gap": wm.get("gap"), "rows": rs}, ensure_ascii=False))
        return
    print(f"knowledge proposals · {len(rs)} · read {wm.get('at') or 'never'}" + (f" · {wm['state']}" if wm.get("state") else ""))
    if wm.get("gap"):
        print(f"  gap: {wm['gap'].get('why')}")
    for r in rs:
        print(f"- {r['claim']}\n    evidence: {r.get('evidence') or '—'}\n    source: {r['source']} · via {', '.join(r['routes'])}"
              f" · thread {r.get('thread') or '—'}")


def main():
    ap = argparse.ArgumentParser(description="mediahub-bot's knowledge proposals in the fact store (read by `ela facts refresh`)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show", help="the proposals the store holds")
    p.add_argument("--hours", type=float, help="only those first seen in the last N hours")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
