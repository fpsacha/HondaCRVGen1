r"""
Engine bay v2 (spec/engine-bay-v2.md): every group module of scripts/bay built into one static mesh,
"engine_block", at its final triangle count, plus the hood's insulator pad joined into the hood. After the
join, bay.visibility drops the faces no camera can see (bottoms, buried walls, backs against the firewall)
and every face is marked no_backfill (no_backs).
Replaces build_engine.py (v1: a full-detail twin projected onto a coarse copy, whose speckle and
smeared lettering the remodel removes). Run by run_rebuild.py once; no twin, so prep keeps it as
built and the bake reads each part's own material colour and decals (self bake).

    exec(compile(open(r"scripts\build_bay.py").read(), "build_bay", "exec"))
"""
import importlib
import os
import sys

import bpy

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
S = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(ROOT, "scripts")
if S not in sys.path:
    sys.path.append(S)                    # run_rebuild already put this checkout's scripts first
import bay  # noqa: E402
from bay import envelope, kit, visibility  # noqa: E402

NAME = "engine_block"
HOOD_PAD_DECAL = {"DecalHoodPad": ("hood_pad.png", ("x", -0.62, 0.62), ("y", 0.98, 1.86), "Grey")}


def no_backs(ob):
    """Every face of the bay is a face of a closed solid (or of one whose missing faces no camera sees,
    bay.visibility): its back is inside the part and never shows. backfill.FORCE_BACKS' boxes round the
    headlamps (meant for the body's open lamp housings and the fender edges) gave 251 faces of the coolant
    bottle, the horn, the hood bumpers and the air box front a flipped copy nobody can see (255 of the 4,835
    shipped triangles until 2026-10-19): backfill.NO_BACKFILL on every face."""
    me = ob.data
    a = me.attributes.get("no_backfill")
    if a is not None:
        me.attributes.remove(a)
    a = me.attributes.new("no_backfill", 'INT', 'FACE')
    a.data.foreach_set("value", [1] * len(me.polygons))


def build():
    for name in (NAME, NAME + "_full", NAME + "_hi"):
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
    ref = bpy.data.objects.get("body")
    col = ref.users_collection[0] if ref else bpy.context.scene.collection
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    b = kit.Bay(col)
    kit.register_decals(HOOD_PAD_DECAL)
    over = []
    for g in bay.GROUPS:
        mod = importlib.import_module("bay." + g)
        kit.register_decals(getattr(mod, "DECALS", {}))
        b.group = g
        mod.build(b)
        t, budget = b.tris(g), getattr(mod, "BUDGET", 0)
        print("engine_block group %-7s %5d tris (budget %d)" % (g, t, budget))
        if budget and t > budget * 1.05:
            over.append("%s %d > %d" % (g, t, budget))
    b.report()
    if not b.objs:
        raise RuntimeError("engine_block: the bay groups built no parts")
    problems = envelope.audit(b.objs)
    ob = b.join(NAME)
    print("engine_block: %d tris as modelled" % kit.tris_of(ob))
    visibility.prune(ob)
    no_backs(ob)
    tris = kit.tris_of(ob)
    print("engine_block: %d faces, %d tris, %d materials" % (len(ob.data.polygons), tris, len(ob.data.materials)))
    if over:
        print("engine_block warning: over budget: " + "; ".join(over))
    if problems:
        print("engine_block warning: %d clearance problems (CLEARANCE lines above)" % len(problems))
    hood = envelope.hood_pad(col, kit.material)
    if hood:
        print("hood + pad: %d faces" % len(hood.data.polygons))
    return ob


build()
