r"""
Update the published Workshop item (mod\workshop.txt id) from mod\ with SteamCMD, without the game.

    python scripts\publish_workshop.py --user STEAM_ACCOUNT_NAME [--note "change note"] [--text] [--dry]

SteamCMD signs in with the session it cached the last time the account logged in by hand. Sign in once
yourself (password and Steam Guard code typed by you, in your own terminal):

    tools\steamcmd\steamcmd.exe +login STEAM_ACCOUNT_NAME +quit

Uploads mod\Contents (the item's mods\HondaCRVGen1 tree, as the game's uploader does) and mod\preview.png.
Title, description and visibility stay as they are on Steam unless --text is given, which also sends
workshop.txt's title and listing\description.txt. --dry writes the VDF and prints the command only.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "mod")
STEAMCMD = os.path.join(ROOT, "tools", "steamcmd", "steamcmd.exe")
APP = "108600"                       # Project Zomboid
VDF = os.path.join(ROOT, "tools", "steamcmd", "crvgen1_item.vdf")


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def workshop_txt():
    out = {}
    with open(os.path.join(MOD, "workshop.txt"), encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                k, v = line.rstrip("\r\n").split("=", 1)
                out.setdefault(k, v)
    return out


def q(s):
    """A VDF string. SteamCMD's reader ends a string at any '"', escaped or not, so quotes in the text become
    curly ones (alternating open/close)."""
    out, open_ = [], True
    for ch in s.replace("\\", "\\\\"):
        if ch == '"':
            out.append("“" if open_ else "”")
            open_ = not open_
        else:
            out.append(ch)
    return '"%s"' % "".join(out)


def main():
    user = _arg("--user") or os.environ.get("STEAM_USER")
    if not user:
        raise SystemExit("publish: --user STEAM_ACCOUNT_NAME (or STEAM_USER); see the docstring for the one-time login")
    ws = workshop_txt()
    item = ws.get("id", "").strip()
    if not item.isdigit():
        raise SystemExit("publish: mod\\workshop.txt has no published id (id=%r)" % item)
    note = _arg("--note", "Update")
    lines = ['"workshopitem"', "{",
             '\t"appid" %s' % q(APP),
             '\t"publishedfileid" %s' % q(item),
             '\t"contentfolder" %s' % q(os.path.join(MOD, "Contents")),
             '\t"previewfile" %s' % q(os.path.join(MOD, "preview.png")),
             '\t"changenote" %s' % q(note)]
    if "--text" in sys.argv:
        with open(os.path.join(ROOT, "listing", "description.txt"), encoding="utf-8") as f:
            desc = f.read().strip()
        lines += ['\t"title" %s' % q(ws.get("title", "")), '\t"description" %s' % q(desc)]
    lines.append("}")
    with open(VDF, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    cmd = [STEAMCMD, "+login", user, "+workshop_build_item", VDF, "+quit"]
    print("PUBLISH item %s from %s\n  %s" % (item, os.path.join(MOD, "Contents"), " ".join(cmd)))
    if "--dry" in sys.argv:
        print(open(VDF, encoding="utf-8").read())
        return
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    print(out[-3000:])
    if "Success" not in out or r.returncode not in (0, 7):
        raise SystemExit("publish: SteamCMD did not report success (exit %d)" % r.returncode)
    print("PUBLISHED https://steamcommunity.com/sharedfiles/filedetails/?id=%s" % item)


if __name__ == "__main__":
    main()
