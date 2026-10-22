r"""
Polish feature (spec/feature-roadmap.md "Function and polish"): the CR-V's own sound, damage textures
painted to its own UV layout, and Project Viewpoint support. Contract: spec/feature-plugins.md.

Sound (research Q6, 42.21 bytecode):
  * mods cannot add FMOD banks, so the engine stays a vanilla RPM-reactive event: VehicleEngineSmallCar
    (Vehicle/Standard/Engine, the small four-cylinder) instead of the SUV template's V6;
  * on top, our own synthesised B20B layer (scripts/features/_polish_sounds.py: two seamless loops,
    idle-to-mid and high revs with the light whine), played by client/HondaCRVGen1_Polish.lua on a
    private world emitter (FMODSoundEmitter.setPitch sets the pitch of EVERY sound on an emitter, so
    the vehicle's own emitter would bend the vanilla engine too), pitched and cross-faded from the
    engine speed, stopped when the engine stops;
  * horn: a 90s Honda dual tone (two notes about a major third apart, ~415 / 520 Hz), looped while the
    horn is held (HornSound plays the script's horn with playSoundLoopedImpl);
  * doors, tailgate, hood: the vanilla sounds (2026-10-22, player feedback "please remove or add option to
    toggle the obnoxious car interaction sounds"): the parts take them from the same vanilla templates as
    the vanilla SUV (Door/part/Door*, TrunkDoor, EngineDoor: VehicleDoorOpenStandard ...). The synthesised
    door clips once merged into the door parts' anim blocks (CRVGen1DoorOpen / Close / Lock / Unlock) are
    gone with their .ogg files and sound scripts; test_gamedata checks no door, gate or hood part names a
    CRVGen1 sound.

Damage (_polish_damage.py): the vehicle shader samples rust, dents, scratches and blood through the
SECOND UV layer, an even xatlas layout of our shell; vanilla's sheets are painted for vanilla's layout.
COMPOSE dumps the shell's triangles with both layouts from crv_kotris.blend (_polish_uv2dump.py, one
short Blender run) and paints five sheets in 3D, looked up per texel: DamageLight (condition 40-59),
DamageHeavy (< 40), RustPanels, Blood + BloodMask. VEHICLE_KEYS points the script at them. Meshes with
no chart of their own in that layout (the decals: `uv2_host`, their UVMap1 borrowed from the panel under
them) are left out of the dump, and any mesh whose UVMap1 is stretched far beyond the shell's texel
density is refused (it would paint its 3D spot over other panels' texels). The shader tints body
damage with the skin texel's own colour (vehicle_crvgen1_norandom, gen_shaders.py); the server Lua
still sets each CR-V's paint HSV to its skin's (the car's keys and anything else reading it).

Project Viewpoint (3809306528, read 2026-10-13; licence: no reuse, read only for compatibility):
  * it captures the vehicle models the game draws and re-shades them with its own copy of the vehicle
    shader, picking the variant by OUR SHADER'S NAME (VehicleCapture.kind, Viewpoint 0.1.6):
    "norandom" -> NO_PAINT, "multiuv" -> MULTI_UV, anything else -> SINGLE_UV, which samples rust /
    damage / blood through the FIRST UV and reads zones 12-15 in the old vehicle.frag order. The shader
    is named vehicle_crvgen1_norandom (2026-10-13): NO_PAINT samples these sheets through UV2 and takes
    the dent hue from the texel, exactly what our norandom shader does in the game;
  * the seated eye sits at the character's head (a per-vehicle offset the player can save in its
    Debug menu); our seats are the script's passenger positions, checked by pzview --eye;
  * furniture tiles are flat sprites unless a model pack binds a model: _polish_viewpoint.py exports the
    picnic table and client/HondaCRVGen1_PolishViewpoint.lua registers the pack when Viewpoint runs.
"""
import os
import re
import subprocess
import sys
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

HERE = os.path.dirname(os.path.abspath(__file__))
BLENDER = _crv_paths.BLENDER
TEXV = "Vehicles/Vehicles_HondaCRVGen1"

# ---------------------------------------------------------------------------------------------
# the vehicle block: the sheets and the sound


def VEHICLE_KEYS(gen, vehicle):
    return {
        "textureRust": TEXV + "_RustPanels",
        "textureDamage1Shell": TEXV + "_DamageLight",
        "textureDamage2Shell": TEXV + "_DamageHeavy",
        "textureDamage1Overlay": TEXV + "_BloodMask",
        "textureDamage2Overlay": TEXV + "_Blood",
        "sound": {
            "alarmLoop": "VehicleAlarmA VehicleAlarmB VehicleAlarmC VehicleAlarmD VehicleAlarmE",
            "engine": "VehicleEngineSmallCar",
            "engineStart": "VehicleEngineSmallCar",
            "engineTurnOff": "VehicleEngineSmallCar",
            "horn": "CRVGen1Horn",
            "ignitionFail": "VehicleIgnitionFailSmallCar",
        },
    }


# ---------------------------------------------------------------------------------------------
# textures

SKIN_HSV_LUA = "shared/HondaCRVGen1_PolishData.lua"


def _skin_hsv(textures, mask_png):
    """Median HSV of the paint on the doors (Mask zone door_fl, gloss = paint) of every shipped skin,
    in the vehicle script's skin order: what the Lua sets as each car's paint colour."""
    import colorsys
    import numpy as np
    from PIL import Image
    sys.path.insert(0, os.path.dirname(HERE))
    import paint_textures as PT
    m = np.asarray(Image.open(mask_png).convert("RGBA"))
    sel = (m[..., 3] == 191) & (np.abs(m[..., :3].astype(int) - [255, 0, 255]).sum(-1) == 0)
    out = []
    for suffix in PT.SKINS:
        t = np.asarray(Image.open(os.path.join(textures, "%s_Shell%s.png" % (PT.NAME, suffix))).convert("RGB"))[sel] / 255.0
        hsv = np.array([colorsys.rgb_to_hsv(*c) for c in t[::40]])
        out.append(tuple(round(float(v), 3) for v in np.median(hsv, 0)))
    return out


def _lua_skin_hsv(root_mod):
    p = os.path.join(root_mod, "42", "media", "lua", *SKIN_HSV_LUA.split("/"))
    if not os.path.exists(p):
        return None
    body = open(p, encoding="utf-8").read()
    return [tuple(float(x) for x in t) for t in re.findall(r"\{\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\s*\}", body)]


def COMPOSE(report, ctx):
    """Dump the shell's two UV layouts from crv_kotris.blend, then paint the damage sheets into ctx['out']."""
    sys.path.insert(0, os.path.dirname(HERE))
    root = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(HERE))
    blend = os.path.join(root, "blender", "crv_kotris.blend")
    npz = os.path.join(ctx["bake"], "polish_uv2.npz")
    names = _shell_objects()
    cmd = [BLENDER, "-b", blend, "--python", os.path.join(HERE, "_polish_uv2dump.py"), "--", npz, ",".join(names)]
    if os.environ.get("CRV_BLENDER_THREADS"):
        cmd[1:1] = ["-t", os.environ["CRV_BLENDER_THREADS"]]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0 or "POLISH uv2dump:" not in out or "Traceback" in out:
        raise RuntimeError("polish: the UV dump failed\n" + "\n".join(out.splitlines()[-20:]))
    report("FEATURE polish: " + next(ln for ln in out.splitlines() if ln.startswith("POLISH uv2dump:")))
    from features import _polish_damage as D
    mask = os.path.join(ctx["bake"], "shell_mask_gloss.png")          # compose: zones + gloss (the shipped Mask is RGB)
    if not os.path.exists(mask):
        mask = os.path.join(ctx["out"], "%s_Mask.png" % D.NAME)
    D.build(npz, mask, ctx["out"], report)
    hsv = _skin_hsv(ctx["out"], mask)
    have = _lua_skin_hsv(os.path.normpath(os.path.join(ctx["out"], "..", "..", "..", "..")))   # .../HondaCRVGen1
    report("FEATURE polish: skin paint HSV %s" % hsv)
    if have is not None and (len(have) != len(hsv) or any(abs(a - b) > 0.04 for h, g in zip(hsv, have) for a, b in zip(h, g))):
        report("FEATURE polish: warning the skins' paint HSV moved: update %s to %s" % (SKIN_HSV_LUA, hsv))


def _shell_objects():
    """bake_atlas.SPACES['shell'] (read as a literal, bake_atlas needs bpy) plus the feature objects on it."""
    import ast
    import features
    tree = ast.parse(open(os.path.join(os.path.dirname(HERE), "bake_atlas.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SPACES" for t in node.targets):
            spaces = features.spaces(ast.literal_eval(node.value))
            return list(spaces["shell"][0])
    raise RuntimeError("polish: no SPACES literal in bake_atlas.py")


# ---------------------------------------------------------------------------------------------
# Lua, media, options

LUA = ["client/HondaCRVGen1_Polish.lua", SKIN_HSV_LUA, "server/HondaCRVGen1_PolishServer.lua",
       "client/HondaCRVGen1_PolishViewpoint.lua"]

SOUND_FILES = ["CRVGen1_EngineLow.ogg", "CRVGen1_EngineHigh.ogg", "CRVGen1_Horn.ogg"]   # the doors: vanilla's (2026-10-22)
MEDIA = (["42/media/scripts/sounds/HondaCRVGen1_PolishSounds.txt"]
         + ["42/media/sound/" + f for f in SOUND_FILES]
         + ["common/media/viewpoint/HondaCRVGen1.properties",
            "common/media/viewpoint/table/table.obj", "common/media/viewpoint/table/table.mtl",
            "common/media/viewpoint/table/texture.png"])

SANDBOX = [
    {"name": "PolishEngineVolume", "type": "integer", "default": 100, "min": 0, "max": 200,
     "label": "CRV engine layer volume (percent)",
     "tooltip": "Loudness of the CRV's own synthesised B20B layer over the game's small-car engine. 0 turns it off."},
]

TRANSLATIONS = {}
