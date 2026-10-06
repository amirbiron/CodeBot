"""כותב המדדים של ``monitoring/metrics_storage.py`` במודול טרי — לטסטים של הכתיבה.

פונקציה ולא fixture (T3), כמו ``_uploads_harness.py``. משמש את
``test_metrics_storage_write_outcomes.py`` (מול דמה) ואת
``test_metrics_storage_flush_mongo.py`` (מול מונגו אמיתי), כדי שהבידוד ייכתב פעם אחת.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

import monitoring


def fresh_writer(monkeypatch, collection: Any):
    """מודול ``metrics_storage`` טרי שכותב לאוסף הנתון, ורשימה שאוספת את האירועים שלו.

    הייבוא הטרי מבודד את מצב המודול — התור, ה-rollups וחותמת הניסיון האחרון.
    ``monkeypatch`` מחזיר בסוף הבדיקה גם את הרשומה ב-``sys.modules`` וגם את התכונה
    על החבילה ``monitoring``: ``from monitoring import metrics_storage`` קורא את
    התכונה, ובלי ההחזרה המודול של הבדיקה היה נשאר למי שבא אחריה.

    כל אירוע נרשם כ-``(event, severity, fields)``.
    """
    for key in ("DISABLE_DB", "DISABLE_METRICS_WRITES", "METRICS_MAX_BUFFER", "METRICS_COLLECTION"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("METRICS_DB_ENABLED", "true")
    monkeypatch.setenv("METRICS_BATCH_SIZE", "50")
    original = getattr(monitoring, "metrics_storage", None)
    monkeypatch.setattr(monitoring, "metrics_storage", original, raising=False)
    monkeypatch.delitem(sys.modules, "monitoring.metrics_storage", raising=False)
    ms = importlib.import_module("monitoring.metrics_storage")

    events = []

    def _collect(event, severity="info", **fields):
        events.append((event, severity, fields))

    monkeypatch.setattr(ms, "emit_event", _collect)
    monkeypatch.setattr(ms, "_get_collection", lambda **_kwargs: collection)
    return ms, events
