"""tvukb offline: bin/kb run in the checkout, every answer headed by the revision and the fetch time; a stale read
fetches first; a checkout that cannot fast-forward says NOT fresh; `kb src` is not offered; no checkout is exit 3."""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="ela-tvukb-")
os.environ["ELA_FACTS_RUNTIME"] = TMP
os.environ.pop("ELA_FACTS_FRESH", None)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "tvukb"))
import tvukb_fixture as KBX  # noqa: E402
import tvukb as T  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


def run(*argv):
    """(exit, stdout, stderr) of tvukb.py with these arguments, in process."""
    out, err = io.StringIO(), io.StringIO()
    sys.argv = ["tvukb.py", *argv]
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            T.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


work, clone = KBX.make(TMP)
T.F.tvukb_checkout = lambda: clone

code, out, err = run("image", "copier:1.0.90")
rev = KBX.head(clone)
check("a first read fetches, then runs kb in the checkout", code == 0 and "kb image copier:1.0.90 at " + rev[:7] in out)
check("the answer is headed by tvu-kb@<sha> and the fetch time", out.splitlines()[0].startswith(f"tvu-kb@{rev[:12]} (fetched ")
      and "NOT fresh" not in out.splitlines()[0])

KBX.push(work)
code, out, err = run("find", "mixer")
check("a read within the facts age does not fetch", KBX.head(clone) == rev)
code, out, err = run("find", "mixer", "--fresh")
check("--fresh fetches and fast-forwards first", KBX.head(clone) == KBX.head(work) and f"tvu-kb@{KBX.head(work)[:12]}" in out)

w = T.F.watermark("tvukb"); w["at"] = "2020-01-01T00:00:00+00:00"
T.F.write_json(os.path.join(T.F.store_dir("tvukb"), "watermark.json"), w)
KBX.push(work, "three")
run("card", "copier")
check("a read older than the facts age fetches first", KBX.head(clone) == KBX.head(work))

code, out, err = run("version", "copier", "1.0.90", "--json")
d = json.loads(out)
check("--json carries the revision, the read time, the arguments, kb's exit and output",
      d["rev"] == KBX.head(clone) and d["read_at"] and d["args"] == ["version", "copier", "1.0.90"] and d["exit"] == 0 and "kb version" in d["output"])
code, out, err = run("sha", "abc")
check("kb's own exit code is passed on", code == 3)

KBX.git(clone, "commit", "-q", "--allow-empty", "-m", "local")     # a local commit: cannot fast-forward
KBX.push(work, "four")
code, out, err = run("find", "x", "--fresh")
check("a checkout that cannot fast-forward answers at its own revision, NOT fresh, and says why",
      code == 0 and "NOT fresh" in out.splitlines()[0] and "not fast-forwarded" in err)

code, out, err = run("src", "media/tvu264")
check("kb src is not offered", code == 2)
check("a subcommand that needs an argument refuses without one", run("image")[0] == 2)

T.F.tvukb_checkout = lambda: os.path.join(TMP, "none")
check("no checkout is exit 3", run("image", "x:1")[0] == 3 and run("status")[0] == 3)

shutil.rmtree(TMP, ignore_errors=True)
print("tvukb offline: " + ("all passed" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
