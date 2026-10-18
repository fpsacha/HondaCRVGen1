r"""
The whole build in one command (system Python):

    python scripts\build.py [--from rebuild|bake|compose|export|scripts|check] [--to ...] [--sync]

Steps, in order:
  rebuild   Blender: split the kotris base, engine bay, liners/bay walls, cabin, prep -> parts_kotris.blend
            (v6: low-poly parts + full-detail '_hi' twins), then holecheck (low vs twins)
  bake      Blender: unwrap + Cycles bakes                                      -> blender/bake, crv_kotris.blend
  compose   Python:  textures                                                   -> mod/.../textures/Vehicles
  export    Blender: rig + FBX                                                  -> mod/.../models_X/vehicles
  scripts   Python:  vehicle script                                             -> mod/.../scripts/vehicles
  overlays  Blender + Python: mechanics overlay images and Lua (vanilla-style schematic, checked against the
            parts' top-down masks, then the window's mouse test replayed under Lua 5.1), accessory icons
            -> mod/.../ui, lua/client, textures; preview -> blender/overlay_raw/_preview.png
  tiles     Blender + Python: picnic table sprite, texture pack, tile definitions, the placed table's 3D
            model + spriteModels.txt -> mod/.../common/media; spriteview (model vs sprite) -> blender/spriteview
  check     Blender: pzview (game-faithful renders + leak counts, _gz files at 150 px/m) -> blender/pzview,
            four shut views rendered natively at the measured 326 px/m (playbook)  -> blender/pzview_326,
            and the same four shut views with textures capped at 512                  -> blender/pzview_cap512
--sync mirrors the mod into the local Zomboid mods folder at the end.
Test builds (a worktree, an experiment): set CRV_ROOT to a scratch data root holding
blender\import\base_honda_cr-v_2001.blend (or parts_kotris.blend to start at the bake),
blender\references\polyhaven, blender\bake (the static decal PNGs: cover_top, hubcap, ...) and a copy
of mod\; every script on the build path then reads and writes there, and the scripts that run are
this checkout's own. Without CRV_ROOT, build.py refuses to run from any checkout but the main one.
Feature plugins (scripts/features/*.py, spec/feature-plugins.md) join every step on their own; CRV_FEATURES
restricts them for a test build ("none", or "lift,decals"), and the run's first line names them.
Each step's key lines are echoed; a step that prints a Traceback stops the build. The bake step
also fails when the shell layout leaves the gate (check_bake: face coverage, panel-island and
fallback densities of the planar shell; no overlapping, out-of-range or starved charts, gaps of at
least 8 px; the paint pass's triangle dump once scripts/uvmesh_dump.py exists). The layout is gated
at the sheet size; the bake images are bake_atlas.SUPERSAMPLE x it (the anti-aliased bake), and the
compose step fails unless every shipped sheet came back to its sheet size with the Mask's zones exact
and the dark cells clean (check_compose).
"""
import os
import re
import subprocess
import sys
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features  # noqa: E402  (scripts/features: the feature plugins every step picks up on its own)

# ROOT is the DATA root (blender/, mod/, tools/): the main checkout, or CRV_ROOT for a test build in
# scratch (every script on the build path honours it). The scripts are always this checkout's own
# (S), so a worktree builds its own code into CRV_ROOT and never touches the main checkout's files.
ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
BLENDER = _crv_paths.BLENDER
MOD = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1")
LOCAL = os.path.expandvars(r"%USERPROFILE%\Zomboid\mods\HondaCRVGen1")
S = os.path.dirname(os.path.abspath(__file__))
STEPS = ["rebuild", "bake", "compose", "export", "scripts", "overlays", "tiles", "check"]
KEEP = re.compile(r"(AUDIT|DONE|EXPORTED|WROTE|FEATURE|COPIED|REMOVED|OVERLAY (rects|ALIGN|preview)|HIT TEST|bake:|reduce:|CLEARANCE|prune|solidify|spike|hub:|trim faces|TOTAL|PZVIEW|low poly|HOLECHECK (TOTAL|hole)|BACKFILL|GLASS|ACCESSORIES|ICON|TILE|SPRITE|well:|sill strips|door lip|seam backing|gate card|door card|dilate:|\bpaint:|\buvmesh:|engine_block|surround|aperture|behind the trim|cargo corner|mud flap|lock hole|wheelhouse|sail backing|belt seal|hood edge|clip translations|CABIN|cabin|_strip|warning|Error|Traceback|line \d+)", re.I)


def run(cmd, label):
    print("== %s" % label, flush=True)
    if cmd[0] == BLENDER and os.environ.get("CRV_BLENDER_THREADS"):   # parallel test builds share the CPU
        cmd = [cmd[0], "-t", os.environ["CRV_BLENDER_THREADS"]] + cmd[1:]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    for line in out.splitlines():
        if KEEP.search(line) and "drawn:" not in line and not line.startswith("Fra:"):   # Cycles' status lines name objects
            print("   " + line[:300])
    if "Traceback" in out or p.returncode != 0:
        tail = "\n".join(out.splitlines()[-30:])
        raise SystemExit("step %s failed (exit %s)\n%s" % (label, p.returncode, tail))
    return out


# The shell sheet's layout gate (spec/planar-texture-plan.md A4). The planar shell (planar_uv) is
# 2048 with panel islands at 3.0 texels/cm and fallback charts at 1.5 x weight; if the pack does
# not fit, both shrink together, never below 2.4 / 1.2 (planar_uv.TPC_FLOOR). Face coverage is the
# share of the sheet under triangles (padding excluded). Measured 2026-10-12 on the shut parts:
# 853 islands, 1,260 fallback charts, 56 cells (57 starved charts made swatches), scale 0.938 ->
# planar 2.83, fallback 1.44 texels/cm, faces 50 % of the sheet (before trim stopped sharing texels
# with paint and starved charts became swatches: 53 % at 0.962; the xatlas shell before it: 40 % at
# 1.22 texels/cm on 1024).
SHELL_FACES_MIN = 45.0               # percent of the sheet: the measured 50 minus 5
SHELL_PLANAR_MIN = 2.4               # texels/cm on the panel islands
SHELL_FALLBACK_MIN = 1.2             # texels/cm at weight 1 on the fallback charts
BAKE_LINE = re.compile(r"bake: shell planar (\d+) islands \((\d+) faces, ([\d.]+) m2, (\d+) in layers 2-3\), (\d+) fallback charts, "
                       r"(\d+) swatch/dark cells, faces (\d+)% of sheet, planar ([\d.]+) texels/cm, fallback ([\d.]+) texels/cm at weight 1")
# the layout's safety numbers (planar_uv.check_layout, printed by bake_atlas.unwrap_planar): no texel
# claimed by two charts, every UV on the sheet, >= 8 px between charts (2 texels after the 512 cap's
# two halvings: planar_uv.GAP_MIN), and no chart too thin to bake its own texels (planar_uv
# STARVE_SHARE: compose's Dilate would fill it from a neighbour, window zones included)
SHELL_GAP_MIN = 8.0
CHECK_LINE = re.compile(r"bake: shell layout check: overlap (\d+) px, out of range (\d+), gap (>=)?([\d.]+) px "
                        r"\((\d+) chart pairs under \d+\), starved fallback charts (\d+), planar islands (\d+)")
UVMESH_DUMP = os.path.join(S, "uvmesh_dump.py")
UVMESH_NPZ = os.path.join(ROOT, "blender", "bake", "shell_uvmesh.npz")


def check_bake(out):
    m = BAKE_LINE.search(out)
    if not m:
        raise SystemExit("bake: no 'bake: shell planar ...' line to check the layout against")
    faces, planar, fallback = float(m.group(7)), float(m.group(8)), float(m.group(9))
    if faces < SHELL_FACES_MIN or planar < SHELL_PLANAR_MIN or fallback < SHELL_FALLBACK_MIN:
        raise SystemExit("bake: shell layout out of range: faces %.0f%% (min %.0f), planar %.2f texels/cm (min %.1f), "
                         "fallback %.2f texels/cm at weight 1 (min %.1f)"
                         % (faces, SHELL_FACES_MIN, planar, SHELL_PLANAR_MIN, fallback, SHELL_FALLBACK_MIN))
    c = CHECK_LINE.search(out)
    if not c:
        raise SystemExit("bake: no 'bake: shell layout check: ...' line to check the layout against")
    overlap, outside, gap = int(c.group(1)), int(c.group(2)), float(c.group(4))
    starved = int(c.group(6)) + int(c.group(7))
    if overlap or outside or gap < SHELL_GAP_MIN or starved:
        raise SystemExit("bake: shell layout unsafe: %d px claimed by two charts, %d faces off the sheet, gap %.1f px "
                         "(min %.0f), %d starved charts (want 0, 0, >= %.0f, 0)"
                         % (overlap, outside, gap, SHELL_GAP_MIN, starved, SHELL_GAP_MIN))
    if os.path.exists(UVMESH_DUMP) and ("bake: shell uvmesh dump ->" not in out or not os.path.exists(UVMESH_NPZ)):
        raise SystemExit("bake: scripts/uvmesh_dump.py is there but the bake wrote no %s: compose would paint "
                         "without the 2D pass" % UVMESH_NPZ)
    print("   bake: shell layout ok (faces %.0f%%, planar %.2f, fallback %.2f texels/cm; overlap 0, gap %.1f px, "
          "0 starved)" % (faces, planar, fallback, gap))


def _const(script, name):
    """A literal constant of one of the scripts (bake_atlas needs bpy to import)."""
    import ast
    tree = ast.parse(open(os.path.join(S, script), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def check_compose():
    """The shipped sheets after the anti-aliased bake (bake_atlas.SUPERSAMPLE, compose's reduce): every
    bake image at its sheet size x SUPERSAMPLE (a stale 1x bake would ship coarse), every shipped sheet
    at its sheet size, the Mask's zones exact legal colours (the shader matches them within 0.01: an
    averaged edge would be no zone), and the dark cells clean (paint_pass.DARK_RGB on every skin,
    nothing lit in them)."""
    import json
    import numpy as np
    from PIL import Image
    spaces, ss = features.spaces(_const("bake_atlas.py", "SPACES")), _const("bake_atlas.py", "SUPERSAMPLE")
    bake = os.path.join(ROOT, "blender", "bake")
    tex = os.path.join(MOD, "common", "media", "textures", "Vehicles")
    name = "Vehicles_HondaCRVGen1"
    bad = []
    for space, (_objs, size) in spaces.items():
        with Image.open(os.path.join(bake, space + "_color.png")) as im:
            if im.size != (size * ss, size * ss):
                bad.append("bake %s_color %dx%d, want %d (sheet %d x %d)" % (space, im.size[0], im.size[1], size * ss, size, ss))
    shell = spaces["shell"][1]
    want = {"Mask": shell, "Lights": shell, "Rust": max(256, shell // 2), "Interior": spaces["interior"][1],
            "Wheel": spaces["wheel"][1], "Engine": spaces["engine"][1]}
    want.update({spec["texture"]: int(spec["size"]) for spec in features.new_spaces().values()})   # the plugins' own sheets
    skins = sorted(f for f in os.listdir(tex) if f.startswith(name + "_Shell") and f.endswith(".png"))
    want.update({f[len(name) + 1:-4]: shell for f in skins})
    for key, size in sorted(want.items()):
        with Image.open(os.path.join(tex, "%s_%s.png" % (name, key))) as im:
            if im.size != (size, size):
                bad.append("%s %dx%d, want %d" % (key, im.size[0], im.size[1], size))
    if bad:
        raise SystemExit("compose: wrong sizes: " + "; ".join(bad))
    zone = _const("bake_atlas.py", "ZONE")
    legal = {(int(round(r * 255)) << 16) | (int(round(g * 255)) << 8) | int(round(b * 255)) for r, g, b in zone.values()}
    legal |= {(int(r * 255 + 0.5) << 16) | (int(g * 255 + 0.5) << 8) | int(b * 255 + 0.5) for r, g, b in zone.values()}
    m = np.asarray(Image.open(os.path.join(tex, name + "_Mask.png")).convert("RGBA"), dtype=np.int32)
    codes = np.unique((m[..., 0] << 16) | (m[..., 1] << 8) | m[..., 2])
    illegal = [c for c in codes.tolist() if c not in legal]
    if illegal:
        raise SystemExit("compose: Mask holds %d colours that are no zone, e.g. %s" % (
            len(illegal), ", ".join("(%d, %d, %d)" % (c >> 16, (c >> 8) & 255, c & 255) for c in illegal[:5])))
    dark = tuple(_const("paint_pass.py", "DARK_RGB"))
    meta_p = os.path.join(bake, "shell_layout_meta.json")
    cells = json.load(open(meta_p, encoding="utf-8")).get("dark_blocks", []) if os.path.exists(meta_p) else []
    rects = []
    for c in cells:
        r = c["rect"]
        rects.append((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]) if isinstance(r, dict) else tuple(r))
    lit = np.asarray(Image.open(os.path.join(tex, name + "_Lights.png")).convert("RGBA"))[..., 3]
    dirty = 0
    for f in skins:
        s = np.asarray(Image.open(os.path.join(tex, f)).convert("RGB"))
        for x0, y0, x1, y1 in rects:
            dirty += int((s[y0:y1, x0:x1] != dark).any(-1).sum())
    for x0, y0, x1, y1 in rects:
        dirty += int((lit[y0:y1, x0:x1] != 0).sum())
    if dirty:
        raise SystemExit("compose: %d texels of the dark cells are not %s (or lit) after the reduction" % (dirty, dark))
    print("   compose: sheets ok (bake %dx, shell %d, interior %d, wheel %d, engine %d); Mask %d zone colours, all legal; "
          "%d dark cells clean on %d skins and the Lights" % (ss, shell, want["Interior"], want["Wheel"], want["Engine"],
                                                             len(codes), len(rects), len(skins)))


def main():
    a = sys.argv[1:]
    if not os.environ.get("CRV_ROOT") and os.path.normcase(S) != os.path.normcase(os.path.join(ROOT, "scripts")):
        raise SystemExit("build.py of %s would write the main checkout's blender/ and mod/ (%s): set CRV_ROOT to a "
                         "scratch data root for a test build" % (os.path.dirname(S), ROOT))
    if "--sync" in a and os.environ.get("CRV_ROOT"):
        raise SystemExit("--sync with CRV_ROOT set: a test build never goes to the game's mods folder")
    first = a[a.index("--from") + 1] if "--from" in a else STEPS[0]
    last = a[a.index("--to") + 1] if "--to" in a else STEPS[-1]
    todo = STEPS[STEPS.index(first):STEPS.index(last) + 1]
    feats = features.load()                        # imported and validated here first: a broken plugin stops the build now
    print("== features: %s" % (", ".join(m.FEATURE for m in feats) if feats else "none"), flush=True)
    for step in todo:
        if step == "rebuild":
            # the engine bay v2's painted decals first (spec/engine-bay-v2.md): build_bay maps them on
            run([sys.executable, os.path.join(S, "paint_bay_decals.py")], step + " (bay decals)")
            run([BLENDER, "-b", os.path.join(ROOT, "blender", "import", "base_honda_cr-v_2001.blend"),
                 "--python", os.path.join(S, "run_rebuild.py")], step)
            run([BLENDER, "-b", os.path.join(ROOT, "blender", "import", "parts_kotris.blend"),     # low vs full detail,
                 "--python", os.path.join(S, "holecheck.py"), "--", "--top", "5"], step + " (holecheck)")  # as the game culls
        elif step == "bake":
            check_bake(run([BLENDER, "-b", os.path.join(ROOT, "blender", "import", "parts_kotris.blend"),
                            "--python", os.path.join(S, "bake_atlas.py")], step))
        elif step == "compose":
            run([sys.executable, os.path.join(S, "compose_textures.py")], step)
            check_compose()
        elif step == "export":
            run([BLENDER, "-b", os.path.join(ROOT, "blender", "crv_kotris.blend"),
                 "--python", os.path.join(S, "run_export.py")], step)
        elif step == "scripts":
            run([sys.executable, os.path.join(S, "gen_scripts.py")], step)
        elif step == "overlays":                       # mechanics-window overlay: the parts' top-down masks,
            run([BLENDER, "-b", os.path.join(ROOT, "blender", "crv_kotris.blend"),          # the schematic drawn
                 "--python", os.path.join(S, "gen_overlays.py")], step + " (render)")       # and checked against
            run([sys.executable, os.path.join(S, "compose_overlays.py")], step + " (compose)")   # them, then the
            run([sys.executable, os.path.join(S, "test_overlay_lua.py")], step + " (hit test)")  # window's mouse test
            run([BLENDER, "-b", os.path.join(ROOT, "blender", "crv_kotris.blend"),        # accessory item icons
                 "--python", os.path.join(S, "gen_icons.py")], step + " (icons)")
        elif step == "tiles":                          # the picnic table's placeable sprite + tile pack
            run([BLENDER, "-b", "--factory-startup", "--python", os.path.join(S, "render_tile.py")], step + " (render)")
            run([sys.executable, os.path.join(S, "tilepack.py")], step + " (pack)")
            run([BLENDER, "-b", "--factory-startup", "--python", os.path.join(S, "spriteview.py")],   # the placed model as the game
                step + " (model on the tile)")                                                       # draws it, against the sprite
            # Project Viewpoint draws a pack-bound tile from the pack's OBJ, never from spriteModels.txt
            # (WorldMesher.drawnElsewhere): re-export it from the world model (it kept the 0.56 m table)
            run([BLENDER, "-b", "--factory-startup", "--python", os.path.join(S, "features", "_polish_viewpoint.py")],
                step + " (Viewpoint table)")
        elif step == "check":
            run([sys.executable, os.path.join(S, "audit_mod.py")], step + " (audit)")
            # --gz 150: every view also saved at 150 px/m (<view>_gz.png, a zoomed-out player); the only files
            # to judge texture at; the second, short run caps textures at 512 the way the loader does
            # for a player on the default Vehicle Texture Size (blender/pzview_cap512)
            run([BLENDER, "-b", "--factory-startup", "--python", os.path.join(S, "pzview.py"), "--", "--close", "--gz", "150"], step + " (pzview)")
            run([BLENDER, "-b", "--factory-startup", "--python", os.path.join(S, "pzview.py"), "--",
                 "--poses", "shut", "--az", "45,135,225,315", "--gz", "150", "--cap", "512",
                 "--out", os.path.join(ROOT, "blender", "pzview_cap512")], step + " (pzview, 512 cap)")
            # the in-game zoom, rendered at it (6.5 m over 2120 px = 326 px/m; --gz only resamples, and
            # upsampling a 215 px/m render shows nothing the render missed): judge the paint here
            run([BLENDER, "-b", "--factory-startup", "--python", os.path.join(S, "pzview.py"), "--",
                 "--poses", "shut", "--az", "45,135,225,315", "--res", "2120",
                 "--out", os.path.join(ROOT, "blender", "pzview_326")], step + " (pzview, 326 px/m)")
    if "--sync" in a:
        print("== sync -> %s" % LOCAL, flush=True)
        r = subprocess.run(["robocopy", MOD, LOCAL, "/MIR", "/NJH", "/NDL", "/NP", "/NFL"], capture_output=True, text=True)
        if r.returncode >= 8:
            raise SystemExit("robocopy failed (%d)\n%s" % (r.returncode, r.stdout[-2000:]))
        print("   synced (robocopy %d)" % r.returncode)
        # the in-game Workshop uploader lists only Zomboid\Workshop\<item> folders (workshop.txt, preview.png,
        # Contents\mods\...), which is exactly the layout of mod\
        ws = os.path.join(os.path.expanduser("~"), "Zomboid", "Workshop", "HondaCRVGen1")
        # the uploader writes the published item's id into ITS workshop.txt: a mirror from a mod\workshop.txt
        # without it would make the next upload a second, new item (it did, 2026-10-18: id 3822496833 wiped)
        def _wid(path):
            try:
                for line in open(path, encoding="utf-8", errors="replace"):
                    if line.startswith("id="):
                        return line[3:].strip()
            except OSError:
                pass
            return ""
        have, ours = _wid(os.path.join(ws, "workshop.txt")), _wid(os.path.join(ROOT, "mod", "workshop.txt"))
        if have and have != ours:
            raise SystemExit("Workshop folder has id=%s but mod\\workshop.txt has id=%r: copy the id into "
                             "mod\\workshop.txt before syncing" % (have, ours))
        r = subprocess.run(["robocopy", os.path.join(ROOT, "mod"), ws, "/MIR", "/NJH", "/NDL", "/NP", "/NFL"],
                           capture_output=True, text=True)
        if r.returncode >= 8:
            raise SystemExit("robocopy to the Workshop folder failed (%d)\n%s" % (r.returncode, r.stdout[-2000:]))
        print("   workshop folder synced -> %s (robocopy %d)" % (ws, r.returncode))
    print("BUILD DONE")


if __name__ == "__main__":
    main()
