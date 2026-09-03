---
name: publish
description: Publish an elak source into the published directory that machines read (Helm's knowledge root, the remote's map) and record the manifest row — today the media docker service catalogue from map/services.yaml. Use on "发布 services.yaml", "更新 Helm 读的服务目录", "publish the catalogue", or after map/services.yaml changed.
user-invocable: true
---

# /ela:publish — from elak to the directory machines read

Self-contained. `publish.py` is the capability; `ela publish …` at the shell is the same thing. Roots
from `site.json`: `records` (elak) and `published` (`<projects>/elak-published`, not a repository).
**The published directory is a subset of elak's own tree** — same paths, elak's names, no per-reader
directories; readers (Helm's context packs, the remote ela) point at these paths.

```bash
P="python3 ${CLAUDE_PLUGIN_ROOT}/skills/publish/publish.py"     # or: ela publish …
$P all            # map/ (yaml, as they are) + the catalogue + <published>/MANIFEST.md; removes stale per-reader dirs
$P catalogue      # map/services.yaml → <published>/knowledge/products/mediahub/services.md + manifest row
$P map            # map/*.yaml + README.md → <published>/map/ (machine-readable; the remote ela's records/map roots)
$P list           # what the manifest says is published, and whether the source's verified: moved since (drift)
```

## Invariants
- **A publication is written, not exported** (elak `publish/README.md`). The document opens by saying what
  it is, and every limit the source states — "the GM registry has not been read first-hand" — appears where
  the reader sees it. The generator carries `source:` and `note:` from the YAML into the document.
- **Nothing under `<published>` is edited by hand.** The location guard blocks it; a change is made in elak
  and published again. The remote receives the directory by rsync with the deploy; it never generates.
- **The manifest row is the record.** `publish/published.md` gets one row per source: source path,
  destination (by root name), published date, the source's `verified:` at that moment. Drift is computed
  from those two dates, never remembered.
- **Only sources that exist in elak.** The team roster, layer rules and voice policy are published when
  `knowledge/products/mediahub/` holds them — not before, and never by copying Helm's files through.
- Helm reads the result only once its knowledge root points at `<published>` (a Helm-repo change, in a
  Helm session); until then the published file is proof of the pipeline, not yet a dependency.
