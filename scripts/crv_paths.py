"""
Where things live on this machine. The project folder is found from this file; Blender and the game are
read from the environment (BLENDER, PZ_GAME) or from local_paths.json at the project root (not in git):

    {"blender": "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe",
     "game": "C:/Program Files (x86)/Steam/steamapps/common/ProjectZomboid"}
"""
import json
import os
import shutil

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _local():
    try:
        with open(os.path.join(PROJECT, "local_paths.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


_LOCAL = _local()
BLENDER = os.environ.get("BLENDER") or _LOCAL.get("blender") or shutil.which("blender") or "blender"
GAME = (os.environ.get("PZ_GAME") or _LOCAL.get("game")
        or r"C:\Program Files (x86)\Steam\steamapps\common\ProjectZomboid")
GAME_MEDIA = os.path.join(GAME, "media")
