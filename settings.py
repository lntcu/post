"""Small local preference file; camera calibration is never persisted."""

import json
import os
from pathlib import Path

SETTINGS_PATH = Path(os.environ.get("POSTURE_MONITOR_SETTINGS", str(Path.home() / ".posture-eye-monitor.json")))
DEFAULTS = {"camera": 0, "view": "auto", "alert_seconds": 5.0,
            "notifications": False}


def load_settings(path=SETTINGS_PATH):
    try:
        saved = json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return DEFAULTS.copy()
    if not isinstance(saved, dict):
        return DEFAULTS.copy()
    settings = DEFAULTS.copy()
    if type(saved.get("camera")) is int and 0 <= saved["camera"] <= 20:
        settings["camera"] = saved["camera"]
    if saved.get("view") in ("auto", "front", "side"):
        settings["view"] = saved["view"]
    if type(saved.get("alert_seconds")) in (int, float) and 0 < saved["alert_seconds"] <= 120:
        settings["alert_seconds"] = float(saved["alert_seconds"])
    if type(saved.get("notifications")) is bool:
        settings["notifications"] = saved["notifications"]
    if isinstance(saved.get("web"), dict):
        # Validate dashboard preferences before restoring them.
        from web_server import WEB_DEFAULTS, validate_preferences
        try:
            web = saved["web"].copy()
            if web.get("writing_assessment") == "image":
                web["writing_assessment"] = "geometry"
            settings = validate_preferences(web, {**settings, "web": WEB_DEFAULTS.copy()})
        except ValueError:
            settings["web"] = WEB_DEFAULTS.copy()
    return settings


def save_settings(settings, path=SETTINGS_PATH):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n")
    temporary.replace(target)
