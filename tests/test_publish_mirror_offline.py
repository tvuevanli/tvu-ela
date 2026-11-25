#!/usr/bin/env python3
"""`publish/mirror.py`: <published> is copied one way into a read-only Obsidian vault with a generated Home.md; a
withdrawn file leaves the mirror, the vault's .obsidian/ survives and takes the working vault's appearance, .git is never carried, and a target that is not a
mirror (or overlaps <published> or the working vault) is refused. Runs in a temporary directory; no site is read."""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "publish"))
import mirror  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)


with tempfile.TemporaryDirectory() as t:
    pub, dst, vault = os.path.join(t, "published"), os.path.join(t, "mirror"), os.path.join(t, "vault")
    put(os.path.join(pub, "README.md"), "# MediaHub knowledge — the team's release\n")
    put(os.path.join(pub, "knowledge", "products", "mediahub", "services.md"), "---\nverified: x\n---\n# Services\n")
    put(os.path.join(pub, "knowledge", "platform", "media", "shm.md"), "no heading here\n")
    put(os.path.join(pub, "lanes", "lanes.md"), "# Lanes\n")
    put(os.path.join(pub, "lanes", "test-list-prod-3.json"), "{}\n")
    put(os.path.join(pub, ".git", "HEAD"), "ref: refs/heads/main\n")
    put(os.path.join(pub, ".gitignore"), "/*\n")
    put(os.path.join(pub, "lanes", ".x.tmp"), "half\n")
    put(os.path.join(vault, "today.md"), "# today\n")

    ok, line = mirror.mirror(pub, dst, vault, dry_run=True)
    check(ok and line.startswith("DRY RUN") and not os.path.exists(dst), "a dry run writes nothing: " + line[:90])

    ok, line = mirror.mirror(pub, dst, vault)
    check(ok and "5 file(s) copied" in line, "the first mirror copies the five published files: " + line[-60:])
    check(os.path.isfile(os.path.join(dst, "knowledge", "products", "mediahub", "services.md")), "a nested note arrives")
    check(not os.path.exists(os.path.join(dst, ".git")), ".git is never carried")
    check(not os.path.exists(os.path.join(dst, ".gitignore")), ".gitignore is never carried")
    check(not os.path.exists(os.path.join(dst, "lanes", ".x.tmp")), "a temporary file is never carried")
    home = open(os.path.join(dst, "Home.md"), encoding="utf-8").read()
    check(mirror.MARKER in home and "Read-only" in home, "Home.md is written, marked and says it is read-only")
    check("[Services](knowledge/products/mediahub/services.md)" in home, "a note is linked by its heading and relative path")
    check("[shm](knowledge/platform/media/shm.md)" in home, "a note with no heading is linked by its name")
    check("[MediaHub knowledge — the team's release](README.md)" in home, "a root note is under Start here")
    check("1 data file(s)" in home and "## lanes" in home, "each top folder is listed, its json counted")
    for rel in [ln.split("](")[1].rstrip(")") for ln in home.splitlines() if ln.startswith("- [") and "](" in ln and "#" not in ln.split("](")[1]]:
        if not os.path.isfile(os.path.join(dst, rel)):
            check(False, f"Home.md link resolves inside the vault: {rel}")

    put(os.path.join(dst, ".obsidian", "app.json"), "{\"reader\": true}\n")
    put(os.path.join(dst, "knowledge", "products", "mediahub", "services.md"), "edited by hand\n")
    os.remove(os.path.join(pub, "knowledge", "platform", "media", "shm.md"))
    ok, line = mirror.mirror(pub, dst, vault)
    check(ok and "1 removed" in line, "a withdrawn file is removed from the mirror: " + line[-60:])
    check(not os.path.exists(os.path.join(dst, "knowledge", "platform", "media", "shm.md")), "the withdrawn note is gone")
    check(open(os.path.join(dst, ".obsidian", "app.json")).read() == "{\"reader\": true}\n", "the vault's .obsidian/ survives")
    check(open(os.path.join(dst, "knowledge", "products", "mediahub", "services.md")).read().endswith("# Services\n"),
          "an edit in the mirror is overwritten")
    check("shm" not in open(os.path.join(dst, "Home.md"), encoding="utf-8").read(), "Home.md drops the withdrawn note")

    other = os.path.join(t, "someone-else")
    put(os.path.join(other, "notes.md"), "mine\n")
    ok, line = mirror.mirror(pub, other, vault)
    check(not ok and "no mirror Home.md" in line and os.path.isfile(os.path.join(other, "notes.md")),
          "a directory that is not a mirror is refused and untouched")
    check(not mirror.mirror(pub, os.path.join(vault, "published"), vault)[0], "a mirror inside the working vault is refused")
    check(not mirror.mirror(pub, os.path.join(pub, "m"), vault)[0], "a mirror inside <published> is refused")
    check(not mirror.mirror(pub, "", vault)[0], "no target: refused")

    import json
    ob = os.path.join(vault, ".obsidian")
    put(os.path.join(ob, "appearance.json"), json.dumps({"cssTheme": "Minimal", "enabledCssSnippets": ["ela"], "baseFontSize": 17}))
    put(os.path.join(ob, "app.json"), json.dumps({"readableLineLength": True, "showLineNumber": True,
                                                  "userIgnoreFilters": ["ela/attachments/"], "newFileLocation": "root"}))
    put(os.path.join(ob, "snippets", "ela.css"), "body { --file-line-width: 94%; }\n.metadata-menu-x { display: none; }\n")
    put(os.path.join(ob, "themes", "Minimal", "theme.css"), "/* theme */\n")
    put(os.path.join(ob, "community-plugins.json"), json.dumps(["metadata-menu", "homepage"]))
    for f in ("workspace.json", "hotkeys.json", "bookmarks.json", "plugins/homepage/data.json"):
        put(os.path.join(ob, f), "{\"secret\": \"x\"}")
    mob = os.path.join(dst, ".obsidian")
    put(os.path.join(mob, "app.json"), json.dumps({"readableLineLength": False, "spellcheck": True}))
    put(os.path.join(mob, "appearance.json"), json.dumps({"enabledCssSnippets": ["mine"], "theme": "obsidian"}))
    ok, line = mirror.mirror(pub, dst, vault, dry_run=True)
    check("would copy" in line and json.load(open(os.path.join(mob, "app.json")))["readableLineLength"] is False,
          "a dry run names the appearance it would copy and writes none of it")
    ok, line = mirror.mirror(pub, dst, vault)
    app, look = json.load(open(os.path.join(mob, "app.json"))), json.load(open(os.path.join(mob, "appearance.json")))
    check(app["readableLineLength"] is True and app["showLineNumber"] is True, "app.json's display keys arrive")
    check(app.get("spellcheck") is True, "the reader's own app.json key in the mirror stays")
    check("userIgnoreFilters" not in app and "newFileLocation" not in app, "app.json's non-display keys are not carried")
    check(look["cssTheme"] == "Minimal" and look["baseFontSize"] == 17 and look["theme"] == "obsidian",
          "appearance.json is merged: the theme and fonts arrive, the reader's other key stays")
    check(look["enabledCssSnippets"] == ["ela", "mine"], "the working vault's snippets are enabled, the reader's own kept")
    check(os.path.isfile(os.path.join(mob, "snippets", "ela.css")) and os.path.isfile(os.path.join(mob, "themes", "Minimal", "theme.css")),
          "snippets/ and themes/ are copied")
    check(not any(os.path.exists(os.path.join(mob, f)) for f in ("workspace.json", "hotkeys.json", "bookmarks.json", "plugins")),
          "workspace, hotkeys, bookmarks and plugins are never copied")
    check("needs a plugin not copied: snippets/ela.css names plugin metadata-menu" in line and "homepage" not in line.split("needs")[1],
          "a snippet that names a community plugin is reported, the plugin not copied")
    ok, line = mirror.mirror(pub, dst, vault)
    check("appearance: unchanged" in line, "a second run finds the appearance unchanged: " + line[-70:])

    log = os.path.join(t, "runtime")
    os.environ["ELA_PUBLISH_MIRROR"] = dst
    out = mirror.after_publish({"published": pub, "vault": vault}, pub, log)
    check(out and out.startswith("mirrored"), "after_publish mirrors and returns its line")
    check(os.path.isfile(os.path.join(log, "publish-mirror.log")), "after_publish logs one line")
    del os.environ["ELA_PUBLISH_MIRROR"]
    check(mirror.after_publish({"published": pub, "published_mirror": dst}, os.path.join(t, "elsewhere"), log) is None,
          "a writer pointed at another root does not touch the site's mirror")
    check(mirror.after_publish({"published": pub}, pub, log) is None, "no published_mirror: nothing happens")

sys.exit(1 if failures else 0)
