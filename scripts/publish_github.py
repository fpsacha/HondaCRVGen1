r"""
Publish the public GitHub repo: a copy of the parts of this project that are about the car and the mod
(README, mod\, scripts\, the listing text and pictures), committed in its own repository next to this one.
The working notes, logs, specs and .blend files stay in this checkout only.

    python scripts\publish_github.py [--message "what changed"] [--dry]

The copy lives in ..\CRV_Gen1_public (its git remote: the public repo). Before committing, every text file
is checked for this machine's user name, home folder and the git e-mail; a hit stops the publish.
Commits use the GitHub no-reply address (PUBLIC_EMAIL).
"""
import fnmatch
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(os.path.dirname(ROOT), "CRV_Gen1_public")
REMOTE = "https://github.com/fpsacha/HondaCRVGen1.git"
PUBLIC_NAME = "fpsacha"
PUBLIC_EMAIL = "41930838+fpsacha@users.noreply.github.com"
INCLUDE = ["README.md", "local_paths.example.json", "mod", "scripts", "listing/description.txt",
           "listing/gallery_jpg"]
SKIP = ["__pycache__", "*.pyc", "local_paths.json"]
TEXT = (".py", ".lua", ".txt", ".md", ".json", ".info", ".vdf", ".glsl", ".vert", ".frag", ".tiles", ".xml")
GITIGNORE = "__pycache__/\n*.pyc\nlocal_paths.json\n"


def _skip(name):
    return any(fnmatch.fnmatch(name, p) for p in SKIP)


def copy_tree():
    for name in os.listdir(PUBLIC):
        if name == ".git":
            continue
        p = os.path.join(PUBLIC, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    for rel in INCLUDE:
        src, dst = os.path.join(ROOT, rel), os.path.join(PUBLIC, rel)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if _skip(n)])
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    with open(os.path.join(PUBLIC, ".gitignore"), "w", encoding="utf-8", newline="\n") as f:
        f.write(GITIGNORE)


def personal_terms():
    home = os.path.expanduser("~")
    user = os.environ.get("USERNAME") or os.path.basename(home)
    email = subprocess.run(["git", "config", "user.email"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    terms = {user, home, home.replace("\\", "/"), email, ROOT, ROOT.replace("\\", "/")}
    return [t for t in terms if t and len(t) >= 4]


def leaks():
    terms = [re.compile(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(t.lower())) for t in personal_terms()]
    hits = []
    for dp, dn, fn in os.walk(PUBLIC):
        dn[:] = [d for d in dn if d != ".git"]
        for f in fn:
            if not f.lower().endswith(TEXT):
                continue
            p = os.path.join(dp, f)
            text = open(p, encoding="utf-8", errors="replace").read().lower()
            for t in terms:
                if t.search(text):
                    hits.append("%s: %r" % (os.path.relpath(p, PUBLIC), t.pattern))
    return hits


def git(*args):
    env = dict(os.environ, GIT_AUTHOR_NAME=PUBLIC_NAME, GIT_AUTHOR_EMAIL=PUBLIC_EMAIL,
               GIT_COMMITTER_NAME=PUBLIC_NAME, GIT_COMMITTER_EMAIL=PUBLIC_EMAIL)
    r = subprocess.run(["git"] + list(args), cwd=PUBLIC, capture_output=True, text=True, env=env)
    if r.returncode:
        raise SystemExit("git %s failed:\n%s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout


def main():
    msg = sys.argv[sys.argv.index("--message") + 1] if "--message" in sys.argv else "Update"
    if not os.path.isdir(os.path.join(PUBLIC, ".git")):
        os.makedirs(PUBLIC, exist_ok=True)
        git("init", "-b", "main")
        git("remote", "add", "origin", REMOTE)
        git("config", "core.autocrlf", "false")
    copy_tree()
    hits = leaks()
    if hits:
        raise SystemExit("publish_github: personal data in the public copy, nothing committed:\n  " + "\n  ".join(hits))
    git("add", "-A")
    if git("status", "--porcelain").strip():
        git("commit", "-q", "-m", msg)
        print(git("log", "--oneline", "-1").strip())
    else:
        print("publish_github: no new changes")
    if "--dry" in sys.argv:
        print("publish_github: --dry, not pushed (%s)" % PUBLIC)
        return
    git("push", "-u", "origin", "main")
    print("publish_github: pushed to %s" % REMOTE)


if __name__ == "__main__":
    main()
