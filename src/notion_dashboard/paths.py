"""Where things live: bundled assets next to the code, the user's config
and token in the platform's config folder (outside the source tree, so
they survive reinstalls and never end up in git).

  Windows: %APPDATA%\\NotionDashboard
  Linux:   $XDG_CONFIG_HOME/notion-dashboard (usually ~/.config/notion-dashboard)

NOTION_DASHBOARD_HOME overrides the config folder.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS = PACKAGE_DIR / "assets"


def config_dir() -> Path:
    override = os.environ.get("NOTION_DASHBOARD_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "NotionDashboard"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "notion-dashboard"


CONFIG_DIR = config_dir()
CONFIG_PATH = CONFIG_DIR / "config.yaml"
ENV_PATH = CONFIG_DIR / ".env"
