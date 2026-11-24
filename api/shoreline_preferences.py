"""Check Shoreline preferences before they are stored on an account (pure, no Flask).

The browser's preferences-model.js normalizes every value when it loads them, so the
server only has to keep the stored blob small and shaped like preferences: an object,
known top-level keys only, plain JSON values, and a size cap. Copy this file to
api/shoreline_preferences.py next to api/shoreline.py.
"""

import json

# Top-level keys the frontend saves (assets/js/shoreline/preferences-model.js).
PREFERENCE_KEYS = frozenset({
    "language", "textSize", "highContrast", "reduceMotion",
    "theme", "customColors", "font", "savedThemes", "readAloud",
})
# Eight saved themes plus settings fit in well under this; it stops someone filling the database.
MAX_PREFERENCES_BYTES = 8000


class PreferencesError(ValueError):
    """The submitted preferences can't be stored; the message is safe to show the user."""


def clean_preferences(raw):
    """Return the storable preferences dict (unknown keys dropped) or raise PreferencesError."""
    if not isinstance(raw, dict):
        raise PreferencesError("Preferences must be a JSON object")
    cleaned = {key: value for key, value in raw.items() if key in PREFERENCE_KEYS}
    try:
        encoded = json.dumps(cleaned, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as err:
        raise PreferencesError("Preferences must be plain JSON values") from err
    if len(encoded.encode("utf-8")) > MAX_PREFERENCES_BYTES:
        raise PreferencesError("Preferences are too large to save")
    return cleaned
