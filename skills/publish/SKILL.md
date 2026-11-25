---
name: publish
description: Publish an elak source into the published directory. Use on "发布 services.yaml", "publish the roster", "花名册改了", "更新 Helm 读的服务目录", "publish the catalogue", or after map/services.yaml changed.
user-invocable: true
---

# /ela:publish — from elak to the directory machines read

Self-contained. `publish.py` is the capability; `ela publish …` at the shell is the same thing. Roots
from `site.json`: `elak` and `published` (`<projects>/elak-published`, a local git repository whose
`.gitignore` versions only the release scope; every rsync excludes `.git`).
**The published directory is a subset of elak's own tree** — same paths, elak's names, no per-reader
directories; readers (Helm's context packs, the remote ela) point at these paths.

```bash
P="python3 ${CLAUDE_PLUGIN_ROOT}/skills/publish/publish.py"     # or: ela publish …
$P all            # map/ (yaml, as they are) + the catalogue + the roster + <published>/MANIFEST.md; removes stale per-reader dirs
$P catalogue      # map/services.yaml → <published>/knowledge/products/mediahub/services.md + manifest row
$P roster         # knowledge/people/{people,responsibilities}.yaml → <published>/knowledge/people/{people.yaml, responsibilities.yaml, roster.md} (identity lines in the shape Helm parses; not Helm's team-map.md, a different document) + manifest row
$P map            # map/*.yaml + README.md → <published>/map/ (machine-readable; the remote ela's records/map roots)
$P doc products/mediahub/team/layer-classification.md   # knowledge/<rel> → <published>/knowledge/<rel>, the elak document verbatim (front matter included) through redact; --reader "…" records who reads it
$P list           # what the manifest says is published, and whether the source's verified: moved since (drift)
$P check          # the release guard over knowledge/platform, knowledge/products, map/ (exit 1 with the lines)
$P release        # due? · what it would commit · the guard — dry run; --apply commits on the owner's signal, never pushes
$P mirror [--dry-run]   # <published> → site.json `published_mirror`, the owner's read-only Obsidian vault (one way, Home.md generated)
```

## Invariants
- **The team's release is facts only** (elak `decisions/2026-11-25-published-knowledge-is-a-versioned-release.md`).
  `check` refuses the owner's word, ruling or reading cited as a source, the owner's first name (read from elak's git
  identity, never written in code), a quotation attributed to a person, a credential, and a quoted CJK sentence outside
  a json or yaml value. A refusal is fixed in elak and published again, never in `<published>`. `release --apply` is
  refused while `check` refuses a line; it records elak's `HEAD` as `elak: <sha>` in the commit, and a release is due
  when elak changed under the scope since that commit. The push to GitLab is the owner's own signal, not a verb.
  `people/`, `lanes/`, `releases/`, `reports/` and `MANIFEST.md` stay outside git (the generated `.gitignore`).
- **A publication is written, not exported** (elak `publish/README.md`). The document opens by saying what
  it is, and every limit the source states — "the GM registry has not been read first-hand" — appears where
  the reader sees it. The generator carries `source:` and `note:` from the YAML into the document.
- **Nothing under `<published>` is edited by hand.** The location guard blocks it; a change is made in elak
  and published again. No other machine receives a copy: the remote ela site retired (elak decision 2026-10-22), and every reader runs on the owner's box.
- **The mirror is a read-only copy for reading, kept current by the writers.** Every subcommand that writes
  `<published>`, `ela release next --write` and `ela teamreport write` refresh `published_mirror` afterwards
  (`mirror.py`): rsync one way with `--delete`, so a withdrawn file leaves the mirror too; the vault's `.obsidian/`,
  `.trash/` and `Home.md` are never deleted; `.git` is never carried. The target is refused when it overlaps
  `<published>` or the working vault, or holds files without the mirror's `Home.md` marker, because `--delete` would
  remove them. The outcome is one line on stderr and in `<runtime>/publish-mirror.log`; a failed mirror never fails
  the publication. Nothing is edited in the mirror: an edit there is overwritten by the next publication.
  The mirror looks like the working vault (site.json `vault`, read, never hard-coded): `appearance.json`, `themes/`,
  `snippets/` and the display keys of `app.json` are merged into the mirror's `.obsidian/`, the reader's other keys
  kept; workspace, plugins, hotkeys and bookmarks are never copied, and a snippet that names a community plugin is
  reported, the plugin not copied.
- **The manifest row is the record.** `publish/published.md` gets one row per source: source path,
  destination (by root name), published date, the source's `verified:` at that moment. Drift is computed
  from those two dates, never remembered.
- **Only sources that exist in elak.** The roster is published (2026-09-03); the layer rules and voice policy follow when
  `knowledge/products/mediahub/` holds them — not before, and never by copying Helm's files through. `doc` refuses a
  `<rel>` that is not a file in elak (exit 2), so a Helm document reaches `<published>` only after it has been written
  into elak's knowledge tree and its facts verified there.
- **A written document is published verbatim, not re-rendered.** `doc` copies the elak source through `redact` only —
  the front matter, and with it the document's own `verified:` and `source:`, is what the reader sees. A source without
  both is refused (exit 2): elak `knowledge/README.md` requires them, and the manifest row's `verified` is read from
  there rather than invented at publication. `all` republishes every document the manifest already records, so a stale
  published copy cannot survive an `ela publish all`, and `list` reports a document's drift by comparing content, not
  dates: `redact(source) != published`, or the published file missing.
- Helm reads the result only once its knowledge root points at `<published>` (a Helm-repo change, in a
  Helm session); until then the published file is proof of the pipeline, not yet a dependency.
