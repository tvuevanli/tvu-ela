# The selectors' replay corpus

One case per file, `<class>/<name>.json`: one wrong proposal a class's selector once made, pinned with its cause, and
the input it was made from, reduced to what the selector reads. `tests/test_dry_corpus_offline.py` replays every case
through its class's selector and fails if the pinned proposal is made again; a selector change merges only with it
green.

A case enters only on the owner's word: his `wrong: <why>` on ela/dry/did.md, or his confirm on an improve item. A
dispute reply or a cancel with no reason reaches him as an improve item first and is never added on its own. The
harvest is improve's; this directory holds the format and the cases.

```json
{
  "class": "link-named",
  "origin": "the batch and line it came from (2026-11-24-link-named-MH-3997#1)",
  "cause": "why the proposal was wrong, in a few words",
  "word": "the owner's word that made it a case (his B on the batch, a did.md wrong: line, an improve confirm)",
  "rejected": {"target": "SCTE-35"},
  "input": {"parent": {"key": "…", "fields": {}}, "children": {"KEY": {"key": "KEY", "fields": {}}},
            "owner": "parent-status only", "today": "parent-status only"}
}
```

`rejected.target` is the ticket the pinned write named; `rejected.type`, when present, narrows it to one link type
(`contains`), so a later proposal of the same ticket under another type is not a repeat. Texts are reduced to the
lines that produced the proposal; hosts are `example.atlassian.net`; people appear as roles.
