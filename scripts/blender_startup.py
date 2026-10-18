r"""
Blender startup script for the CRV_Gen1 project.

Run automatically by launch_blender.bat. Does four things:
  1. enables the BlenderMCP addon if this Blender has it installed but not ticked
  2. hard-asserts BlenderMCP telemetry is OFF (the addon ships default-on)
  3. starts the BlenderMCP socket server so no N-panel clicking is needed
  4. puts scripts/ on sys.path so the project modules are importable

Never runs in --background: the addon refuses to serve there anyway.
"""

import os
import sys

import bpy

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
SCRIPTS = os.path.join(PROJECT, "scripts")
ADDON = "blender_mcp"
PORT = 9876

if SCRIPTS not in sys.path:
    sys.path.append(SCRIPTS)


def _enable_addon():
    """The addon file lives in the user addons folder; enabling is per-userpref."""
    if bpy.context.preferences.addons.get(ADDON) is not None:
        print("CRV: BlenderMCP addon already enabled")
        return True
    try:
        bpy.ops.preferences.addon_enable(module=ADDON)
    except Exception as exc:                       # noqa: BLE001
        print(f"CRV: could not enable {ADDON}: {exc}")
        return False
    ok = bpy.context.preferences.addons.get(ADDON) is not None
    print("CRV: BlenderMCP addon enabled" if ok else "CRV: BlenderMCP addon NOT found "
          "(expected APPDATA/Blender Foundation/Blender/4.5/scripts/addons/blender_mcp.py)")
    return ok


def _force_telemetry_off():
    """Fail loudly rather than silently uploading prompts/code/screenshots."""
    try:
        entry = bpy.context.preferences.addons.get(ADDON)
        if entry is None:
            print("CRV: BlenderMCP addon not enabled — nothing to secure")
            return None
        prefs = entry.preferences
        if getattr(prefs, "telemetry_consent", False):
            prefs.telemetry_consent = False
            print("CRV: telemetry consent was ON — forced OFF")
        else:
            print("CRV: telemetry consent confirmed OFF")
        return False
    except Exception as exc:                       # noqa: BLE001
        print(f"CRV: WARNING could not verify telemetry consent: {exc}")
        return None


def _start_server():
    try:
        scene = bpy.context.scene
        if hasattr(scene, "blendermcp_port"):
            scene.blendermcp_port = PORT
        if getattr(scene, "blendermcp_server_running", False):
            print(f"CRV: BlenderMCP server already running on localhost:{PORT}")
            return None
        bpy.ops.blendermcp.start_server()
        print(f"CRV: BlenderMCP server started on localhost:{PORT}")
    except Exception as exc:                       # noqa: BLE001
        print(f"CRV: could not auto-start MCP server ({exc}). "
              f"Start it by hand: viewport > N > MCP for Blender > Start MCP Server")
    return None


def main():
    if bpy.app.background:
        print("CRV: background mode — skipping MCP server start")
        return
    if _enable_addon():
        _force_telemetry_off()
        try:
            bpy.ops.wm.save_userpref()             # keep the addon ticked for plain launches too
        except Exception as exc:                   # noqa: BLE001
            print(f"CRV: could not save userpref: {exc}")
    # Defer: operators need a fully built window context.
    bpy.app.timers.register(_start_server, first_interval=1.0)


main()
