"""A tvu-kb checkout for the offline tests: a bare origin and a clone whose skills/tvu-kb/bin/kb echoes its arguments
and the revision it runs at. No network."""
import os, subprocess


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example"})


def head(cwd):
    return subprocess.run(["git", "-C", cwd, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def make(tmp):
    """(origin work tree, clone): a commit is made in the work tree and pushed to the bare origin with `push(work)`."""
    bare, work, clone = (os.path.join(tmp, n) for n in ("origin.git", "work", "clone"))
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", work], check=True)
    kb = os.path.join(work, "skills", "tvu-kb", "bin")
    os.makedirs(kb)
    with open(os.path.join(kb, "kb"), "w") as f:
        f.write('#!/bin/bash\necho "kb $* at $(git rev-parse --short HEAD)"\n[ "$1" = sha ] && exit 3\nexit 0\n')
    open(os.path.join(work, "skills", "tvu-kb", "SKILL.md"), "w").write("method\n")
    git(work, "add", "-A"); git(work, "commit", "-qm", "one"); git(work, "remote", "add", "origin", bare); git(work, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", bare, clone], check=True)
    return work, clone


def push(work, name="two"):
    open(os.path.join(work, name), "w").write(name)
    git(work, "add", "-A"); git(work, "commit", "-qm", name); git(work, "push", "-q", "origin", "main")
