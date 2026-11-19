---
name: tvukb
description: Media image tag → its module commits (tvu-kb). For "镜像是哪个 commit".
user-invocable: true
---

# /ela:tvukb — from a lane to the media commit it runs

tvu-kb is the media team's knowledge base: their Jenkins catalogue, every build's module commits (kept after
Jenkins drops a build, the old Jenkins and SVN eras included), and a card per project and image. ela does not copy
it. `ela tvukb <sub>` runs the checkout's own `bin/kb` and heads every answer with `tvu-kb@<sha> (fetched …)`; cite
that line with the claim, as any first-hand read is cited.

**The method is theirs.** Which subcommand answers which question, and how a card's age is judged against the
catalogue, is `<code>/media/tvu-kb/skills/tvu-kb/SKILL.md` (`ela tvukb status` prints its path). Read it before the
first question of a session. Its `kb src` is not offered here: the source at a commit is read in ela's own checkout of
that repository (`ela map` says where), so there is one copy of the media code, not three.

**What ela adds is the join**, which neither side holds alone:

1. the lane's bundle and its docker services' versions: `ela release bundle <bundle>` (the lane's bundle from
   `ela matrix` or `ela docker`); the GM name maps to the image through `<published>/map/services.yaml`
   (`gm_names`, `slugs`, `process_types`);
2. the image tag → its build and every module commit: `ela tvukb image <image>:<tag>`, or a program version →
   the same: `ela tvukb version <program> <version>`;
3. the fix's commit against that module commit: ancestry in ela's checkout of the module
   (`git merge-base --is-ancestor <fix> <built>`), the code read at the built commit with `/ela:probe`.

The answer names all three hops and the revision of each source. A hop that cannot be read is said as a gap, never
bridged by a guess: an image with no tvu-kb build, a module ela has no checkout of, a GM name not in the map.

## Freshness

The media team's Jenkins hook commits to tvu-kb several times a day, and a stale checkout maps a tag to the wrong
build. `ela facts refresh` fetches and fast-forwards the checkout once a pass (source `tvukb`, its watermark the
revision and the read time); a read older than `ELA_FACTS_MAX_AGE` hours fetches first, and `--fresh` always does.
`NOT fresh` in the head line means the fetch failed or the checkout could not fast-forward: say so with the answer.

## What it is not for

tvu-kb holds the media builds' provenance. A graph's process type or a GM name → an image is the map's
(`services.yaml`), and which service answers an app-layer endpoint is the app code's; a card that is missing or
behind its repository is said as such, and the code at the built commit is read instead.
