import json
import os

SETTINGS_PATH = os.path.expanduser('~/.oci-policy-analysis/settings.json')


def load_settings():
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_settings(settings: dict):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception:
        # Silent failure is OK for settings writes in this app
        pass
