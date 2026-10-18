r"""
Compile the mod's vehicle shaders on this machine's GPU driver before the game ever sees them.

    python scripts\check_shaders.py

The game's #include lines are resolved the way its loader does in effect (the .glsl bodies are
pulled in once each); the vertex/fragment pair is then compiled and linked with moderngl in a
standalone context. The stock vehicle_multiuv pair is compiled first as the control: if the
control fails, the harness is wrong, not the shader.
"""
import os
import re
import sys

import moderngl
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(_crv_paths.GAME, "media", "shaders")
MOD = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "shaders")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_shaders import NAME  # noqa: E402  (vehicle_crvgen1_norandom: the vehicle* prefix picks the game's vehicle texture cap)


def _read(path):
    return open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")


def resolve(src, seen):
    out = []
    for line in src.split("\n"):
        m = re.match(r'\s*#include\s+"([^"]+)"', line)
        if not m:
            out.append(line)
            continue
        name = m.group(1)
        if name in seen:
            out.append("// (include %s already pulled in)" % name)
            continue
        seen.add(name)
        found = False
        for cand in (name + ".h", name + ".glsl", name):      # the game pairs a .h (constants,
            p = os.path.join(GAME, cand)                       # prototypes) with a .glsl body
            if os.path.exists(p):
                found = True
                body = "\n".join(l for l in _read(p).split("\n") if not l.strip().startswith("#version"))
                out.append("// ---- include %s\n%s\n// ---- end %s" % (cand, resolve(body, seen), cand))
        if not found:
            out.append("#error missing include %s" % name)
    return "\n".join(out)


def compile_pair(label, vert, frag):
    ctx = moderngl.create_context(standalone=True)
    v = resolve(_read(vert), set())
    f = resolve(_read(frag), set())
    try:
        prog = ctx.program(vertex_shader=v, fragment_shader=f)
    except Exception as exc:                        # noqa: BLE001
        print("FAIL %s\n%s" % (label, exc))
        return False
    uniforms = sorted(n for n in prog if isinstance(prog[n], moderngl.Uniform))
    print("OK   %-44s uniforms: %s" % (label, ", ".join(uniforms)))
    return True


def main():
    ok = True
    ok &= compile_pair("control: vehicle_multiuv_static + frag",
                       os.path.join(GAME, "vehicle_multiuv_static.vert"), os.path.join(GAME, "vehicle_multiuv.frag"))
    ok &= compile_pair("control: vehicle_multiuv_noreflect (skinned)",
                       os.path.join(GAME, "vehicle_multiuv_noreflect.vert"), os.path.join(GAME, "vehicle_multiuv_noreflect.frag"))
    for vert in (NAME + "_static.vert", NAME + ".vert"):
        ok &= compile_pair("mod: %s + %s.frag" % (vert, NAME),
                           os.path.join(MOD, vert), os.path.join(MOD, NAME + ".frag"))
    print("SHADERS", "ALL OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
