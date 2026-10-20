r"""
KI5-style rig for the CR-V: one armature, one bone per opening panel, one baked clip per panel.

    import rig_vehicle, importlib; importlib.reload(rig_vehicle); rig_vehicle.build()

Why bones and not object origins: vanilla B42 doors never visibly open, because a vanilla vehicle
is a single mesh. KI5's do, because each panel is its own object bound to a bone with
`boneWeight = <bone> 1.0` in the script, and the script plays a clip that ships inside the FBX
(`anim Open { anim = door_fl_opening }`). See spec/pz-conventions.md section 7.

Every bone here points ALONG its own hinge axis, so opening a panel is a single rotation about the
bone's local Y. Children ride their parent: the windows on their doors, the flip-up glass on the
tailgate, exactly the way the real two-piece CR-V tailgate behaves.

Model space: metres, +Y front, +Z up, +X vehicle right, origin at ground level between the axles.
"""
import math
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
if _HERE and _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import features  # noqa: E402  (scripts/features: feature meshes that ride a bone)

ARMATURE = "VehicleSkeleton"
FRAME_OPEN = 25                        # clips run frame 1 (shut) -> FRAME_OPEN (fully open)

X_DOOR = 0.845                         # hinge line, just inside the body side
Y_HINGE_F, Y_HINGE_R = 0.80, -0.28     # front door on the fender seam, rear door on the B-pillar
Z_HINGE = (0.35, 1.35)
Y_TG_HINGE, X_TG_HINGE = -2.11, 0.69   # tailgate is side-hinged at the RIGHT edge of the gate
Z_TG_HINGE = (0.74, 1.13)
Y_TG_GLASS, Z_TG_GLASS = -1.70, 1.64   # flip-up glass hinges at the FRONT edge of the roof strip above it, which lifts with the glass
Y_HOOD_HINGE, Z_HOOD_HINGE = 0.86, 1.12   # just behind the kotris hood's rear edge (y 0.87, z 1.13)

# name -> (hinge point, parent). Every bone points along +Y with zero roll, so its rest rotation
# exports as identity (KI5 does the same). Reason: the game ignores an animation channel's default
# value, and the FBX exporter drops constant channels, so a bone with a non-zero rest rotation
# would get zeros substituted the moment its clip animates only one axis. Hinges therefore turn
# about the bone's LOCAL X (= world X) or LOCAL Z (= world Z); windows slide along local -Z.
# Window bones sit ON their door bone so their rest translation is zero as well.
BONE_LEN = 0.30
HINGES = {
    "body_bone":      ((0.0, 0.0, 0.0), None),
    "hood_bone":      ((0.0, Y_HOOD_HINGE, Z_HOOD_HINGE), "body_bone"),
    "door_fl_bone":   ((-X_DOOR, Y_HINGE_F, Z_HINGE[0]), "body_bone"),
    "door_fr_bone":   ((X_DOOR, Y_HINGE_F, Z_HINGE[0]), "body_bone"),
    "door_rl_bone":   ((-X_DOOR, Y_HINGE_R, Z_HINGE[0]), "body_bone"),
    "door_rr_bone":   ((X_DOOR, Y_HINGE_R, Z_HINGE[0]), "body_bone"),
    "window_fl_bone": ((-X_DOOR, Y_HINGE_F, Z_HINGE[0]), "door_fl_bone"),
    "window_fr_bone": ((X_DOOR, Y_HINGE_F, Z_HINGE[0]), "door_fr_bone"),
    "window_rl_bone": ((-X_DOOR, Y_HINGE_R, Z_HINGE[0]), "door_rl_bone"),
    "window_rr_bone": ((X_DOOR, Y_HINGE_R, Z_HINGE[0]), "door_rr_bone"),
    "trunk_bone":     ((X_TG_HINGE, Y_TG_HINGE, Z_TG_HINGE[0]), "body_bone"),
    # the RD1's flip-up rear glass hinges on the roof edge (the BODY, not the side-hinged gate) and
    # lifts with the tailgate: it rides the trunk clip on its own bone
    "trunkglass_bone": ((0.0, Y_TG_GLASS, Z_TG_GLASS), "body_bone"),
}
# Gas struts on the flip-up glass (2026-10-17, the RD1 reference photos): one each side, from the D-pillar's
# inner face below the glass to the glass's inner face. Right-side points (metres, shut); the left mirrors x.
# The tube rides strut_*_tube_bone (on the body), the rod strut_*_rod_bone (a child of the glass bone); every
# frame of trunk_opening aims each at the other end (strut_rotations), so the rod slides in the tube: neither
# is longer than the shut length (no end pokes past the other's eye) and together they overlap >= 6 cm open.
# Until 2026-10-20 the body end sat low (0.585, -1.89, 1.20) and the glass end 20 cm in from the glass's side.
# 2026-10-20 (the owner, first person: "the strut for the window is weirdly placed": it ran diagonally across the
# glass from the pillar's foot to 20 cm in). The RD1's struts lie along the D-pillars: the body end is now HIGH on
# the pillar trim's face (2.2 cm off it, under the roof corner), the glass end low on the glass at the same x, so
# the shut strut runs down the trim's rear edge (x 0.48 against the edge's 0.50-0.57) and, seen from the cabin,
# stands parallel to the pillar. A low body end cannot work: opening, the strut tilts back through the trim's rear
# edge (z 1.39-1.41) by 5-10 mm whatever the glass end (scratch strut_search4/5, exact clearances over the travel:
# only x 0.41 cleared). This pair clears body and interior by >= 7.6 mm over the whole swing, both sides; shut
# 0.312 m between the ends, open 0.434 m.
STRUT_B = (0.48, -1.85, 1.50)
STRUT_G = (0.48, -1.987, 1.22)
STRUT_TUBE, STRUT_ROD = 0.26, 0.24
STRUT_R_TUBE, STRUT_R_ROD, STRUT_EYE = 0.011, 0.0045, 0.014
STRUTS = {side: ((sx * STRUT_B[0], STRUT_B[1], STRUT_B[2]), (sx * STRUT_G[0], STRUT_G[1], STRUT_G[2]))
          for side, sx in (("r", 1.0), ("l", -1.0))}
for _side, (_b, _g) in STRUTS.items():
    HINGES["strut_%s_tube_bone" % _side] = (_b, "body_bone")
    HINGES["strut_%s_rod_bone" % _side] = (_g, "trunkglass_bone")
STRUT_BONES = [n for side in STRUTS for n in ("strut_%s_tube_bone" % side, "strut_%s_rod_bone" % side)]

# The hood's prop rod (2026-10-17, review OPEN-7: the hood stood at 62 degrees with nothing under it). Stowed
# along the tie bar's rear top edge (bay front group: the pivot bracket at the bar's left end, the clip at x 0.17),
# pivoting at the bar's LEFT end as in lhd_03 (the propped rod rises by the left headlamp, leaning back). It rides
# prop_rod_bone (on the body) and is joined into the hood mesh, so the hood's model (gen_scripts HOOD_BONES) masks
# the hood track to both bones, like the gate's struts. Every frame of hood_opening keys the rod's swing
# (prop_rotations): it turns about the pivot from the stowed line toward the slot, never higher than the rising
# hood lets it (its surface keeps PROP_CLEAR off the underside), and drops its tip into the slot in the last frame.
# 62 degrees puts the hood's underside 0.89 m from the pivot at its nearest: the rod is 0.92 m, so stowed it runs
# 7 cm past the bar's right end (over the right lamp's back, under the hood); the slot is where the underside at
# x PROP_TIP_X is PROP_LEN - PROP_EMBED from the pivot, ahead of the nearest point (the rod leans back ~38 deg).
# Stowed, the rod lies on the bar's top rear edge (y TIE_Y0 + 7 mm, z tie top + r: front.py) from its bent pivot
# end to the tip, short of the right lamp's back strip; the bend drops into the pivot bracket at the bar's left
# end, whose top stays under the hood limit (~0.89 there). It turns about PROP_PIVOT, the bend's foot.
PROP_PIVOT = (-0.428, 1.842, 0.880)
PROP_BEND = (-0.420, 1.842, 0.9005)
PROP_TIP0 = (0.485, 1.842, 0.9005)
PROP_LEN = math.dist(PROP_PIVOT, PROP_TIP0)
PROP_R = 0.0045
PROP_TIP_X = -0.395                     # the slot's x: the rod leans 2 cm inboard
PROP_EMBED = 0.006                      # the tip's end sits this far into the hood's underside (pad) in the slot
PROP_CLEAR = 0.004                      # metres between the rod's surface and the hood while it swings up
PROP_SLOT_FALLBACK = (-0.395, 1.270, 1.632)   # the open slot if the hood mesh is missing (measured 2026-10-17)
HINGES["prop_rod_bone"] = (PROP_PIVOT, "body_bone")
PROP_BONES = ["prop_rod_bone"]
# Hood hinge straps (2026-10-17, review BAY-9: the static arms in the bay stayed put and pointed at empty air
# with the hood up). One black strap per side under the hood's rear corner, riding hood_bone: along the underside
# to the rear edge, then a lug down toward the hinge base (bay_walls, top z 1.025 at y 0.92-1.00), so it swings
# up with the hood. It cannot run on back to the hinge axis (y 0.86, z 1.12): under the cowl there the cabin's
# dash reaches forward to y ~0.89 (a first try poked through it). The strap stays ahead of the firewall top
# (y >= 0.99). 2026-10-17 round 2 (R2-BAY-4): the lug ran 5 cm down toward the base, and with the hood open it
# hung in mid-air (its end ~19 cm over the base): it is now a 2 cm flange turned down at the strap's rear end, a
# bracket on the hood's underside that reads the same shut or open. (y, drop) points: drop = metres below the
# strap's line under the skin (1 mm under the hood's lowest surface there); the x of each strap is
# +/- HOOD_STRAP_X, its section HOOD_STRAP_W (x) by HOOD_STRAP_T.
HOOD_STRAP_X, HOOD_STRAP_W, HOOD_STRAP_T = 0.552, 0.010, 0.009
HOOD_STRAP_PTS = [(1.095, 0.0), (1.004, 0.0), (0.999, 0.020)]

BONES ={name: (head, (head[0], head[1] + BONE_LEN, head[2]), parent) for name, (head, parent) in HINGES.items()}

# mesh object -> bone that drives it
SKIN = {
    "body": "body_bone", "hood": "hood_bone",
    "door_fl": "door_fl_bone", "door_fr": "door_fr_bone",
    "door_rl": "door_rl_bone", "door_rr": "door_rr_bone",
    "window_fl": "window_fl_bone", "window_fr": "window_fr_bone",
    "window_rl": "window_rl_bone", "window_rr": "window_rr_bone",
    "trunk": "trunk_bone",
    # the flip-up glass and its guard ride trunkglass_bone. Their parts (WindshieldRear and
    # CRVGuardWindshieldRear) share TrunkDoor's AnimationPlayer through `parent = TrunkDoor`, and the
    # gate's model script names trunkglass_bone in its boneWeight mask (gen_scripts), so the
    # trunk_opening track drives this bone. Skinned to it WITHOUT that mask entry both drew nowhere
    # in game (2026-10-12): a bone with weight 0 on every track gets an identity transform
    "trunk_top": "trunkglass_bone",
    # window guards (build_accessories.py) are bolted to the door frames: they swing with the door
    # (each guard part is a child of its door, whose track weights door_*_bone) and stay put when
    # the window rolls down; the rear glass guard rides the flip-up glass the same way
    "acc_guard_fl": "door_fl_bone", "acc_guard_fr": "door_fr_bone",
    "acc_guard_rl": "door_rl_bone", "acc_guard_rr": "door_rr_bone",
    "acc_guard_rear": "trunkglass_bone",
    # the soft spare-tyre cover swings with the side-hinged gate (part CRVSpareCover, parent = TrunkDoor:
    # drawn by the gate's player, whose track weights trunk_bone)
    "acc_spare_cover": "trunk_bone",
}
for _side in STRUTS:                      # make_struts builds them, join_struts merges them into the glass
    SKIN["strut_%s_tube" % _side] = "strut_%s_tube_bone" % _side
    SKIN["strut_%s_rod" % _side] = "strut_%s_rod_bone" % _side
# the hood's riders (make_hood_riders / join_hood_riders, called by make_struts / join_struts): joined into the hood
SKIN["hood_prop_rod"] = "prop_rod_bone"
SKIN["hood_strap_l"] = "hood_bone"
SKIN["hood_strap_r"] = "hood_bone"
# the feature plugins' meshes that ride a bone (scripts/features OBJECTS bone): only bones above, no new clips
SKIN.update(features.skin())
_unknown = sorted(b for b in SKIN.values() if b not in HINGES)
if _unknown:
    raise ValueError("rig_vehicle: feature meshes ride bones the rig does not have: %s" % ", ".join(_unknown))

# clip name -> [(bone, channel, value at FRAME_OPEN), ...]. "rot_x"/"rot_z": rotation about the
# bone's local X / Z in radians (= world X / Z, see HINGES); "slide_z": translation along local -Z,
# metres. A clip may move several bones: the game plays one clip per part (TrunkDoor), and the
# CR-V's tailgate is two pieces, the side-hinged gate and the flip-up glass.
CLIPS = {
    "hood_opening":      [("hood_bone", "rot_x", math.radians(62))],   # panel lies in FRONT of its hinge: positive lifts it
    "door_fl_opening":   [("door_fl_bone", "rot_z", math.radians(-68))],
    "door_fr_opening":   [("door_fr_bone", "rot_z", math.radians(68))],
    "door_rl_opening":   [("door_rl_bone", "rot_z", math.radians(-68))],
    "door_rr_opening":   [("door_rr_bone", "rot_z", math.radians(68))],
    "window_fl_opening": [("window_fl_bone", "slide_z", 0.44)],
    "window_fr_opening": [("window_fr_bone", "slide_z", 0.44)],
    "window_rl_opening": [("window_rl_bone", "slide_z", 0.40)],
    "window_rr_opening": [("window_rr_bone", "slide_z", 0.40)],
    "trunk_opening":     [("trunk_bone", "rot_z", math.radians(105)),   # real RD1 gates open to ~100-110 deg: out and away from the opening
                          ("trunkglass_bone", "rot_x", math.radians(-70))],   # glass lies BEHIND its hinge: negative lifts it
}


# The glass follows the gate (2026-10-17 round 2, R2-OC-7). Both used to swing on their own eased keys, and at
# 5-10 % of the clip the gate's top edge, by its hinge, passed through the lifting glass's lower edge. Holding the
# gate until the glass is ~10 deg up was worse: from 1 to 3 deg the glass's lower edge sweeps back through the
# shut gate's top lip, whatever the gate's angle below ~35 deg. A map of the shipped meshes (both rotated rigidly
# about the rig's hinges, gate 0-40 x glass 0-8 deg, face-pair overlaps) shows the way through: the glass stays
# shut while the gate starts out, takes half a degree while the gate goes from 3 to 5 deg, and is past that band
# (3.5 deg) by the time the gate is at 7.5. From there it rises in step with the gate, to its full angle with the
# gate's. GLASS_ON_GATE: (gate deg, glass deg) points, linear between; the last point is the clip's full angles.
# Every frame of the glass is keyed from the gate's eased curve (linear between frames), and the struts are aimed
# at the glass as it then plays, as before.
# Round 3 (R2-OC-7 remainder): that way through closed again once the glass's seam ring (trunk_top's SeamBack ring,
# hanging 2 cm under the pane's lower edge, in front of the gate's top lip) was taken into account: any lift of the
# glass while the gate's hinge-side top corner is still under it (0.5 deg was enough) swept the ring rearward through
# the corner's lip, shell and rim (gate 5.75-7 deg; with the lift held to gate 15-30 deg the contact only moved with
# it). With the glass held shut the opening gate never touches it (prep_parts GATE_CARD_Z keeps the card's top under
# the ring), and from ~33 deg of gate on the corner has swung clear: a sweep of the prepared parts (gate every
# 0.25 deg about the rig's hinge, the glass on this map) found no contact for a hold to 33 deg or more. The glass now waits for the gate
# to reach 40 deg, then rises with it to its full angle.
GLASS_ON_GATE = [(0.0, 0.0), (40.0, 0.0)]


def _glass_on_gate(gate_deg):
    pts = GLASS_ON_GATE + [(math.degrees(abs(_gate_angle())), math.degrees(abs(_glass_angle())))]
    if gate_deg <= pts[0][0]:
        return pts[0][1]
    for (g0, l0), (g1, l1) in zip(pts, pts[1:]):
        if gate_deg <= g1:
            return l0 + (l1 - l0) * (gate_deg - g0) / max(1e-9, g1 - g0)
    return pts[-1][1]


def _glass_follows_gate(arm):
    """trunk_opening: key trunkglass_bone on every frame from the gate's angle there (GLASS_ON_GATE)."""
    sc = bpy.context.scene
    f_was = sc.frame_current
    gates = []
    for f in range(1, FRAME_OPEN + 1):
        sc.frame_set(f)
        gates.append(arm.pose.bones["trunk_bone"].rotation_euler.z)
    sc.frame_set(f_was)
    pb = arm.pose.bones["trunkglass_bone"]
    sign = 1.0 if _glass_angle() >= 0 else -1.0
    out = []
    for f, a in zip(range(1, FRAME_OPEN + 1), gates):
        g = sign * math.radians(_glass_on_gate(math.degrees(abs(a))))
        _apply(pb, "rot_x", g)
        pb.keyframe_insert("rotation_euler", frame=f)
        pb.keyframe_insert("location", frame=f)
        out.append((math.degrees(abs(a)), math.degrees(abs(g))))
    _apply(pb, "rot_x", 0.0)
    for fc in arm.animation_data.action.fcurves:
        if fc.data_path.startswith('pose.bones["trunkglass_bone"]'):
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'
            fc.update()
    print("GATECLIP trunk_opening: gate / glass deg by frame: %s"
          % ", ".join("%d %.1f/%.1f" % (f, a, b) for f, (a, b) in zip(range(1, FRAME_OPEN + 1), out) if f <= 8 or f % 4 == 1))


def _apply(pb, channel, value):
    """Set one pose bone from a clip channel spec."""
    pb.rotation_euler = (0.0, 0.0, 0.0)
    pb.location = (0.0, 0.0, 0.0)
    if channel == "rot_x":
        pb.rotation_euler = (value, 0.0, 0.0)
    elif channel == "rot_z":
        pb.rotation_euler = (0.0, 0.0, value)
    elif channel == "slide_z":
        pb.location = (0.0, 0.0, -value)


def _clear():
    for name in (ARMATURE,):
        ob = bpy.data.objects.get(name)
        if ob:
            bpy.data.objects.remove(ob, do_unlink=True)
    for arm in list(bpy.data.armatures):
        if arm.users == 0:
            bpy.data.armatures.remove(arm)
    for act in list(bpy.data.actions):
        if act.name in CLIPS:
            bpy.data.actions.remove(act)


def _collection():
    c = bpy.data.collections.get("rig")
    if c is None:
        c = bpy.data.collections.new("rig")
        bpy.context.scene.collection.children.link(c)
    return c


def build_armature():
    _clear()
    arm_data = bpy.data.armatures.new(ARMATURE)
    arm = bpy.data.objects.new(ARMATURE, arm_data)
    _collection().objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    made = {}
    for name in BONES:                                     # parents first
        pass
    order = sorted(BONES, key=lambda n: 0 if BONES[n][2] is None else (1 if BONES[BONES[n][2]][2] is None else 2))
    for name in order:
        head, tail, parent = BONES[name]
        b = arm_data.edit_bones.new(name)
        b.head, b.tail = head, tail
        b.use_connect = False
        if parent:
            b.parent = made[parent]
        made[name] = b
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in arm.pose.bones:
        pb.rotation_mode = 'XYZ'
    return arm


def skin(arm):
    """One vertex group per part at weight 1.0, plus an Armature modifier. KI5 does exactly this."""
    done = []
    for obj_name, bone in SKIN.items():
        ob = bpy.data.objects.get(obj_name)
        if ob is None:
            continue
        for vg in list(ob.vertex_groups):
            ob.vertex_groups.remove(vg)
        vg = ob.vertex_groups.new(name=bone)
        vg.add(range(len(ob.data.vertices)), 1.0, 'REPLACE')
        for m in list(ob.modifiers):
            if m.type == 'ARMATURE':
                ob.modifiers.remove(m)
        m = ob.modifiers.new("Armature", 'ARMATURE')
        m.object = arm
        if ob.parent is not arm:
            ob.parent = arm
            ob.matrix_parent_inverse = arm.matrix_world.inverted()
        done.append(obj_name)
    return done


def bake_clips(arm):
    """One action per opening panel, each pushed to its own NLA track so the FBX carries them all."""
    if arm.animation_data is None:
        arm.animation_data_create()
    for t in list(arm.animation_data.nla_tracks):
        arm.animation_data.nla_tracks.remove(t)
    made = []
    for clip, specs in CLIPS.items():
        act = bpy.data.actions.new(clip)
        arm.animation_data.action = act
        for bone, channel, value in specs:
            pb = arm.pose.bones[bone]
            _apply(pb, channel, 0.0)
            pb.keyframe_insert("rotation_euler", frame=1)
            pb.keyframe_insert("location", frame=1)
            _apply(pb, channel, value)
            pb.keyframe_insert("rotation_euler", frame=FRAME_OPEN)
            pb.keyframe_insert("location", frame=FRAME_OPEN)
            _apply(pb, channel, 0.0)
        if clip in ("trunk_opening", "hood_opening"):
            # the riders follow the panel's angle as the clip actually plays it: the two keys above interpolate
            # with Blender's default (Bezier: an eased swing), and the FBX bakes every frame, so each frame's
            # angle is read back from the action, not assumed linear (2026-10-17: the struts were aimed for a
            # linear glass, ~6 degrees ahead of it at a quarter of the swing)
            panel, full = (("trunkglass_bone", _glass_angle()) if clip == "trunk_opening"
                           else ("hood_bone", _hood_angle()))
            riders = STRUT_BONES if clip == "trunk_opening" else PROP_BONES
            if clip == "trunk_opening":
                _glass_follows_gate(arm)
            sc = bpy.context.scene
            f_was = sc.frame_current
            angles = []
            for f in range(1, FRAME_OPEN + 1):
                sc.frame_set(f)
                angles.append(arm.pose.bones[panel].rotation_euler.x)
            sc.frame_set(f_was)
            prev = {}
            lifts = [0.0]
            for f, a in zip(range(1, FRAME_OPEN + 1), angles):
                frac = max(0.0, min(1.0, a / full)) if abs(full) > 1e-9 else 0.0
                if clip == "trunk_opening":
                    rots = strut_rotations(frac, prev)
                else:
                    lifts.append(1.0 if f == FRAME_OPEN else (0.0 if f == 1 else _prop_lift(a, lifts[-1])))
                    rots = prop_rotations(lifts[-1], prev)
                for bone, e in rots.items():
                    pb = arm.pose.bones[bone]
                    pb.rotation_euler = e
                    pb.location = (0.0, 0.0, 0.0)
                    pb.keyframe_insert("rotation_euler", frame=f)
                    pb.keyframe_insert("location", frame=f)
                prev = rots
            if clip == "hood_opening":
                print("PROPROD hood_opening: hood %s deg, rod lift %s (frames 1, 5, .. 25)" % (
                    ", ".join("%.0f" % math.degrees(a) for a in angles[::4]),
                    ", ".join("%.2f" % s for s in lifts[1::4])))
            for bone in riders:
                arm.pose.bones[bone].rotation_euler = (0.0, 0.0, 0.0)
        track = arm.animation_data.nla_tracks.new()
        track.name = clip
        track.strips.new(clip, 1, act)
        track.mute = True
        arm.animation_data.action = None
        made.append(clip)
    return made


def pose(arm, opened=(), frame=FRAME_OPEN):
    """Preview: put the named clips at their open frame and everything else shut."""
    for clip, specs in CLIPS.items():
        for bone, channel, value in specs:
            pb = arm.pose.bones[bone]
            _apply(pb, channel, value if clip in opened else 0.0)
    rots = strut_rotations(1.0 if "trunk_opening" in opened else 0.0)
    rots.update(prop_rotations(1.0 if "hood_opening" in opened else 0.0))
    for bone, e in rots.items():
        if bone in arm.pose.bones:
            arm.pose.bones[bone].rotation_euler = e
    bpy.context.view_layer.update()


def _gate_angle():
    return next(v for b, _c, v in CLIPS["trunk_opening"] if b == "trunk_bone")


def _glass_angle():
    return next(v for b, _c, v in CLIPS["trunk_opening"] if b == "trunkglass_bone")


def _hood_angle():
    return next(v for b, _c, v in CLIPS["hood_opening"] if b == "hood_bone")


# ---------------------------------------------------------------------------------------------- the prop rod
_PROP = {}           # cache: the hood's BVH (rest, without the riders), the slot, the swing axis and angle


def _hood_hinge():
    from mathutils import Vector
    return Vector((0.0, Y_HOOD_HINGE, Z_HOOD_HINGE))


def _hood_tree():
    """BVH of the hood mesh at rest (model metres), less any faces riding prop_rod_bone (a hood the rod has
    already been joined into)."""
    from mathutils.bvhtree import BVHTree
    hood = bpy.data.objects.get("hood")
    if hood is None or not len(hood.data.polygons):
        return None
    me = hood.data
    vg = hood.vertex_groups.get("prop_rod_bone")
    skip = set()
    if vg is not None:
        for v in me.vertices:
            if any(g.group == vg.index and g.weight > 0.0 for g in v.groups):
                skip.add(v.index)
    M = hood.matrix_world
    co = [M @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons if not (skip and any(i in skip for i in p.vertices))]
    return BVHTree.FromPolygons(co, polys)


def _prop_setup():
    """The slot (the rod's tip with the hood fully open), the swing axis and angle: the rod turns about the
    pivot in the plane of its stowed line (+x) and its propped direction."""
    if _PROP:
        return _PROP
    from mathutils import Matrix, Vector
    P, H = Vector(PROP_PIVOT), _hood_hinge()
    tree = _hood_tree()
    R = Matrix.Rotation(_hood_angle(), 3, 'X')
    want = PROP_LEN - PROP_EMBED
    slot = None
    if tree is not None:
        samples = []                    # the opened underside along x = PROP_TIP_X, rear to front
        for i in range(0, 241):
            y = 0.95 + i * 0.004
            hit = tree.ray_cast(Vector((PROP_TIP_X, y, 0.3)), Vector((0.0, 0.0, 1.0)))
            if hit[0] is not None:
                q = H + R @ (hit[0] - H)
                samples.append(((q - P).length, q))
        if samples:                     # the crossing AHEAD of the nearest point (the pad's rear edge makes others)
            k0 = min(range(len(samples)), key=lambda k: samples[k][0])
            for (da, qa), (db, qb) in zip(samples[k0:], samples[k0 + 1:]):
                if da < want <= db:
                    slot = qa.lerp(qb, (want - da) / max(1e-9, db - da))
                    break
    if slot is None:
        print("PROPROD warning: no slot on the hood mesh, using the fallback %s" % (PROP_SLOT_FALLBACK,))
        slot = Vector(PROP_SLOT_FALLBACK)
    d0 = (Vector(PROP_TIP0) - P).normalized()
    d1 = (slot - P).normalized()
    _PROP.update(tree=tree, slot=slot, d0=d0, d1=d1, axis=d0.cross(d1).normalized(), theta=d0.angle(d1))
    print("PROPROD slot (open) at (%.3f, %.3f, %.3f), %.3f m from the pivot; the rod swings %.1f deg"
          % (slot.x, slot.y, slot.z, (slot - P).length, math.degrees(_PROP["theta"])))
    return _PROP


def _prop_dir(s):
    from mathutils import Quaternion
    g = _prop_setup()
    return Quaternion(g["axis"], s * g["theta"]) @ g["d0"]


def _prop_clear(s, a):
    """True if the rod lifted a fraction s of its swing keeps PROP_CLEAR off the hood opened by angle a (rad):
    samples along its axis, taken into the hood's rest frame, see no hood above them (along the hood's own up)
    within PROP_R + PROP_CLEAR and none below (below = through the skin, or into the gap over the pad)."""
    from mathutils import Matrix, Vector
    g = _prop_setup()
    tree = g["tree"]
    if tree is None:
        return True
    P, H = Vector(PROP_PIVOT), _hood_hinge()
    Rinv = Matrix.Rotation(-a, 3, 'X')
    d = _prop_dir(s)
    up, down = Vector((0.0, 0.0, 1.0)), Vector((0.0, 0.0, -1.0))
    for k in range(1, 41):
        p = P + d * (PROP_LEN * k / 40)
        q = H + Rinv @ (p - H)
        dn = tree.ray_cast(q, down, 0.25)
        if k >= 38:
            # the tip's last 7 cm slide along the underside into the slot: they may touch it and sink in up to
            # the slot's depth (the rod meets the underside at a shallow angle: kept PROP_CLEAR off, it would
            # stop ~10 cm short of the slot until the last frame and snap in)
            # (inside the pad the ray down meets the pad's down-facing bottom; through the pad or the skin it would
            # meet an up-facing top)
            if dn[0] is not None and (dn[3] > PROP_EMBED + 0.001 or dn[1].z > -0.3):
                return False
            continue
        h = tree.ray_cast(q, up)
        if h[0] is not None and h[3] < PROP_R + PROP_CLEAR:
            return False
        if dn[0] is not None:
            return False
    return True


def _prop_lift(a, s_prev, step=0.005):
    """How far up its swing (0 stowed .. 1 in the slot) the rod can be with the hood at angle a: raised from
    s_prev in small steps while it stays clear (the hood only moves away as it opens, so this never drops)."""
    s = s_prev
    while s + step <= 1.0 and _prop_clear(s + step, a):
        s += step
    return s


def prop_rotations(s, prev=None):
    """{prop_rod_bone: Euler}: the rod lifted a fraction s of its swing. The bone points along +Y at rest with
    world axes (HINGES), so its pose rotation is the rod's world rotation about the pivot."""
    from mathutils import Quaternion
    g = _prop_setup()
    m = Quaternion(g["axis"], s * g["theta"]).to_matrix()
    p = prev.get("prop_rod_bone") if prev else None
    return {"prop_rod_bone": m.to_euler('XYZ', p) if p is not None else m.to_euler('XYZ')}


def strut_rotations(t, prev=None, angle=None):
    """{bone: Euler} with the glass a fraction t of its way open (the clip is linear in angle). Bones point
    along +Y at rest, axes = world axes, so a tube bone's pose rotation is its world rotation; a rod bone's is
    relative to the glass bone, which turns about world X through the glass hinge."""
    from mathutils import Matrix, Vector
    a = (_glass_angle() if angle is None else angle) * t
    piv = Vector((0.0, Y_TG_GLASS, Z_TG_GLASS))
    rx = Matrix.Rotation(a, 3, 'X')
    out = {}
    for side, (b, g) in STRUTS.items():
        b, g = Vector(b), Vector(g)
        gt = piv + rx @ (g - piv)
        d0, dt = (g - b).normalized(), (gt - b).normalized()
        tube = d0.rotation_difference(dt).to_matrix()
        rod_world = (-d0).rotation_difference((b - gt).normalized()).to_matrix()
        rod = rx.inverted() @ rod_world
        for bone, m in (("strut_%s_tube_bone" % side, tube), ("strut_%s_rod_bone" % side, rod)):
            p = prev.get(bone) if prev else None
            out[bone] = m.to_euler('XYZ', p) if p is not None else m.to_euler('XYZ')
    return out


def _rod_uv():
    """UV (shell sheet) of the most even neutral grey (mean 110..180 of 255) under the body's Chrome faces."""
    import numpy as np
    root = os.environ.get("CRV_ROOT") or os.path.dirname(_HERE)
    path = os.path.join(root, "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "textures", "Vehicles",
                        "Vehicles_HondaCRVGen1_Shell.png")
    body = bpy.data.objects.get("body")
    if body is None or not os.path.exists(path):
        return None
    im = bpy.data.images.load(path, check_existing=True)
    w, h = im.size
    pix = np.empty(w * h * 4, dtype=np.float32)
    im.pixels.foreach_get(pix)
    pix = pix.reshape(h, w, 4)[..., :3]
    me = body.data
    names = [m.name if m else "" for m in me.materials]
    uv = me.uv_layers[0].data
    best = None
    for p in me.polygons:
        if names[p.material_index] != "Chrome":
            continue
        us = [uv[li].uv for li in p.loop_indices]
        u = sum(a[0] for a in us) / len(us)
        v = sum(a[1] for a in us) / len(us)
        x, y = int(u * w), int(v * h)
        if not (3 <= x < w - 3 and 3 <= y < h - 3):
            continue
        patch = pix[y - 3:y + 4, x - 3:x + 4] * 255.0
        mean = patch.reshape(-1, 3).mean(axis=0)
        spread = float(patch.max() - patch.min())
        if 110 <= mean.mean() <= 180 and mean.max() - mean.min() < 10 and (best is None or spread < best[0]):
            best = (spread, (u, v))
    bpy.data.images.remove(im)
    return best[1] if best else None


def _dark_uv():
    """UV (shell sheet) of the body's dark block: the centre of its largest uv_island -2 face in UV."""
    body = bpy.data.objects.get("body")
    if body is None or not body.data.uv_layers:
        return None
    me = body.data
    isl = me.attributes.get("uv_island")
    if isl is None:
        return None
    vals = [0] * len(me.polygons)
    isl.data.foreach_get("value", vals)
    uv = me.uv_layers[0].data
    best = None
    for p in me.polygons:
        if vals[p.index] != -2:
            continue
        us = [uv[li].uv for li in p.loop_indices]
        area = abs(sum(us[i][0] * us[(i + 1) % len(us)][1] - us[(i + 1) % len(us)][0] * us[i][1]
                       for i in range(len(us)))) / 2
        if best is None or area > best[0]:
            best = (area, (sum(u[0] for u in us) / len(us), sum(u[1] for u in us) / len(us)))
    return best[1] if best else None


def _rider_object(name, data, like, uvs, collection):
    """A mesh object from (verts, faces) with `like`'s materials and UV layers; uvs: [uv per face] (every
    corner of a face samples one point of the sheet)."""
    v, f = data
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(p) for p in v], [], [tuple(x) for x in f])
    me.validate()
    for m in like.data.materials:
        me.materials.append(m)
    for layer in like.data.uv_layers:
        ul = me.uv_layers.new(name=layer.name)
        for p in me.polygons:
            for li in p.loop_indices:
                ul.data[li].uv = uvs[p.index] if uvs[p.index] is not None else (0.0, 0.0)
    for p in me.polygons:
        p.use_smooth = False
    me.update()
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


def _strap_data(pts, x, w, t):
    """A flat strap along a (y, z) polyline at x: a w (x) by t section, mitred at the bends, capped."""
    from mathutils import Vector
    P = [Vector((0.0, y, z)) for y, z in pts]
    n = len(P)
    rings = []
    for i in range(n):
        ds = []
        if i > 0:
            ds.append((P[i] - P[i - 1]).normalized())
        if i < n - 1:
            ds.append((P[i + 1] - P[i]).normalized())
        tan = sum(ds, Vector()).normalized()
        nrm = Vector((0.0, -tan.z, tan.y))                    # in-plane normal of the path
        k = 1.0
        if len(ds) == 2:
            k = 1.0 / max(0.5, ds[0].dot(tan))                # keep the thickness through a bend
        off = nrm * (t / 2 * k)
        rings.append([(x - w / 2, P[i].y + s * off.y, P[i].z + s * off.z) for s in (-1, 1)]
                     + [(x + w / 2, P[i].y + s * off.y, P[i].z + s * off.z) for s in (1, -1)])
    v = [c for r in rings for c in r]
    f = []
    for i in range(n - 1):
        a, b = 4 * i, 4 * (i + 1)
        for k in range(4):
            k2 = (k + 1) % 4
            f.append((a + k, a + k2, b + k2, b + k))
    f.append((3, 2, 1, 0))
    f.append((4 * (n - 1), 4 * (n - 1) + 1, 4 * (n - 1) + 2, 4 * (n - 1) + 3))
    return v, f


def _orient_outward(ob):
    """Consistent outward normals on a closed rider mesh (the game culls back faces)."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()


def make_hood_riders(report=print):
    """The hood's riders at the shut pose (see PROP_* and HOOD_STRAP_* above): the prop rod stowed along the
    tie bar (a grey steel rod with a black grip, prop_rod_bone) and the two hinge straps (hood_bone). Built at
    export on the hood's materials and UV layers, each face sampling one even texel of the shell sheet: the
    rod a neutral mid grey (_rod_uv, as the gate struts' rods), the grip and straps the dark block."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from bay import kit
    hood = bpy.data.objects.get("hood")
    if hood is None:
        return []
    _PROP.clear()
    _prop_setup()                       # the slot is measured on the hood before anything rides it
    grey, dark = _rod_uv(), _dark_uv()
    if grey is None:
        grey = dark
    col = hood.users_collection[0]
    made = []
    P, Bd, T = Vector(PROP_PIVOT), Vector(PROP_BEND), Vector(PROP_TIP0)
    d = (T - Bd).normalized()
    leg = kit.cyl_data(tuple(P), tuple(Bd + (Bd - P).normalized() * PROP_R), PROP_R, 8)   # the bent end, into the bracket
    rod = kit.cyl_data(tuple(Bd - d * PROP_R), tuple(T), PROP_R, 8)
    grip = kit.cyl_data(tuple(Bd + d * 0.30), tuple(Bd + d * 0.40), PROP_R + 0.0025, 8)
    v, f = kit.merge(leg, rod, grip)
    uvs = [grey] * (len(leg[1]) + len(rod[1])) + [dark] * len(grip[1])
    ob = _rider_object("hood_prop_rod", (v, f), hood, uvs, col)
    _orient_outward(ob)
    made.append(ob.name)
    # straps: under the hood's skin (its lowest surface there, 1 mm under), less each point's drop
    me = hood.data
    tree = BVHTree.FromPolygons([hood.matrix_world @ q.co for q in me.vertices], [tuple(p.vertices) for p in me.polygons])
    for side, sx in (("l", -1.0), ("r", 1.0)):
        x = sx * HOOD_STRAP_X
        pts = []
        for y, drop in HOOD_STRAP_PTS:
            hit = tree.ray_cast(Vector((x, y, 0.3)), Vector((0.0, 0.0, 1.0)))
            z = (hit[0].z if hit[0] is not None else 1.11) - 0.001 - HOOD_STRAP_T / 2 - drop
            pts.append((y, z))
        data = _strap_data(pts, x, HOOD_STRAP_W, HOOD_STRAP_T)
        ob = _rider_object("hood_strap_" + side, data, hood, [dark] * len(data[1]), col)
        _orient_outward(ob)
        made.append(ob.name)
    report("HOODRIDERS %s: %d faces (prop rod %.2f m on prop_rod_bone, hinge straps on hood_bone)"
           % (", ".join(made), sum(len(bpy.data.objects[n].data.polygons) for n in made), PROP_LEN))
    return made


def join_hood_riders(report=print):
    """After skin(): merge the riders into the hood, keeping their vertex groups (bones), so the hood model draws
    them on the hood track (its boneWeight list names prop_rod_bone: gen_scripts HOOD_BONES)."""
    hood = bpy.data.objects.get("hood")
    parts = [bpy.data.objects.get(n) for n in ("hood_prop_rod", "hood_strap_l", "hood_strap_r")]
    parts = [o for o in parts if o is not None]
    if hood is None or not parts:
        return 0
    bpy.ops.object.select_all(action='DESELECT')
    for o in parts:
        o.select_set(True)
    hood.select_set(True)
    bpy.context.view_layer.objects.active = hood
    bpy.ops.object.join()
    report("HOODRIDERS joined into hood: vertex groups %s" % ", ".join(vg.name for vg in hood.vertex_groups))
    return len(parts)


def make_struts(report=print):
    """The four strut meshes at the shut pose: a black tube from the body end, a chrome rod from the glass end,
    an eye at each end. Materials and both UV layers follow the glass mesh (trunk_top), which they are joined
    into: the tube samples the glass's dark block (uv_island -2), the rod one of its chrome faces.
    Also builds the hood's riders (make_hood_riders: the prop rod and the hinge straps)."""
    import bmesh
    from mathutils import Vector
    make_hood_riders(report)
    glass = bpy.data.objects.get("trunk_top")
    if glass is None:
        return []
    me = glass.data
    names = [m.name if m else "" for m in me.materials]
    isl = me.attributes.get("uv_island")
    vals = [0] * len(me.polygons)
    if isl is not None:
        isl.data.foreach_get("value", vals)
    uv0 = me.uv_layers[0].data

    def face_uv(pred):
        for p in me.polygons:
            if pred(p):
                us = [uv0[li].uv for li in p.loop_indices]
                return (sum(u[0] for u in us) / len(us), sum(u[1] for u in us) / len(us)), p.material_index
        return None, 0
    dark_uv, dark_mat = face_uv(lambda p: vals[p.index] == -2)
    # the rod: an even, neutral mid grey of the shell sheet (the glass's own "chrome" faces sample the stop
    # lamp's red housing: the first build drew red struts). Found on the body's Chrome faces, which share
    # the glass's sheet, by sampling the composed texture round each face's UV centre.
    chrome_uv, chrome_mat = _rod_uv(), dark_mat
    if chrome_uv is None:
        chrome_uv = dark_uv
    made = []
    for side, (b, g) in STRUTS.items():
        b, g = Vector(b), Vector(g)
        d = (g - b).normalized()
        for part, start, direction, length, radius, uv, mi in (
                ("tube", b, d, STRUT_TUBE, STRUT_R_TUBE, dark_uv, dark_mat),
                ("rod", g, -d, STRUT_ROD, STRUT_R_ROD, chrome_uv, chrome_mat)):
            bm = bmesh.new()
            q = Vector((0, 0, 1)).rotation_difference(direction)
            for z0, z1, r in ((0.0, length, radius), (-STRUT_EYE / 2, STRUT_EYE / 2, radius * 1.6)):
                res = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=r, radius2=r, depth=z1 - z0)
                for v in res["verts"]:
                    v.co = start + q @ (v.co + Vector((0, 0, (z0 + z1) / 2)))
            for f in bm.faces:
                f.material_index = mi
            obm = bpy.data.meshes.new("strut_%s_%s" % (side, part))
            bm.to_mesh(obm)
            bm.free()
            for m in me.materials:
                obm.materials.append(m)
            for layer in me.uv_layers:
                ul = obm.uv_layers.new(name=layer.name)
                for li in range(len(obm.loops)):
                    ul.data[li].uv = uv if uv is not None else (0.0, 0.0)
            ob = bpy.data.objects.new(obm.name, obm)
            glass.users_collection[0].objects.link(ob)
            made.append(ob.name)
    report("STRUTS %d meshes, %d faces (tube %.2f m on the body, rod %.2f m on the glass, each side)"
           % (len(made), sum(len(bpy.data.objects[n].data.polygons) for n in made), STRUT_TUBE, STRUT_ROD))
    return made


def join_struts(report=print):
    """After skin(): merge the strut meshes into the glass, keeping their vertex groups (bones), so the glass
    model (child part WindshieldRear, drawn by the gate's player) draws them. Also joins the hood's riders."""
    join_hood_riders(report)
    glass = bpy.data.objects.get("trunk_top")
    parts = [bpy.data.objects.get("strut_%s_%s" % (side, k)) for side in STRUTS for k in ("tube", "rod")]
    parts = [o for o in parts if o is not None]
    if glass is None or not parts:
        return 0
    bpy.ops.object.select_all(action='DESELECT')
    for o in parts:
        o.select_set(True)
    glass.select_set(True)
    bpy.context.view_layer.objects.active = glass
    bpy.ops.object.join()
    report("STRUTS joined into trunk_top: vertex groups %s" % ", ".join(vg.name for vg in glass.vertex_groups))
    return len(parts)


def build():
    arm = build_armature()
    skinned = skin(arm)
    clips = bake_clips(arm)
    print("VehicleSkeleton: %d bones, %d parts skinned, %d clips" %
          (len(arm.data.bones), len(skinned), len(clips)))
    print("  bones: " + ", ".join(b.name for b in arm.data.bones))
    print("  clips: " + ", ".join(clips))
    return arm


if __name__ == "__main__":
    build()
