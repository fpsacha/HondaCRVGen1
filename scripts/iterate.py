r"""
One iteration of the blueprint loop, run inside Blender (via BlenderMCP):

    import iterate, importlib; importlib.reload(iterate); iterate.step("h3_")

  1. re-trace the blueprint with the system Python (PIL/numpy live there)
  2. rebuild the hull body from the trace
  3. render the calibrated ortho views + a 3/4 view
  4. score against the blueprint with ortho_diff and print the IoU table
"""
import importlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
PREVIEW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_")))), "blender", "iterate")


def _sys_python(args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run(["python"] + args, cwd=ROOT, capture_output=True, text=True, env=env)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out.strip()


def step(prefix, retrace=True, persp=True):
    if SCRIPTS not in sys.path:
        sys.path.append(SCRIPTS)
    if retrace:
        code, out = _sys_python([os.path.join(SCRIPTS, "trace_blueprint.py")])
        print("[trace]", out if code == 0 else "FAILED\n" + out)
    import build_body, build_body_hull, compare_ortho, render_ortho
    for m in (build_body, build_body_hull, compare_ortho, render_ortho):
        importlib.reload(m)
    build_body_hull.build()
    pxm, views = compare_ortho.views_from_calibration()
    compare_ortho.VIEWS = views
    compare_ortho.render_all(prefix=prefix)
    if persp:
        render_ortho.render(prefix=prefix, out_dir=PREVIEW, views=[
            ("persp_fl", 'PERSP', (-4.6, 5.6, 2.2), (0.0, 0.1, 0.85), None, (1600, 1000), 35),
            ("persp_rr", 'PERSP', (4.8, -5.4, 2.1), (0.0, -0.3, 0.85), None, (1600, 1000), 35),
        ])
    code, out = _sys_python([os.path.join(SCRIPTS, "ortho_diff.py"), os.path.join(ROOT, "export", "ortho_cmp"), prefix])
    print("[score]\n" + "\n".join(l for l in out.splitlines() if "IoU" in l or "missing" in l))
