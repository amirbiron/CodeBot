#!/usr/bin/env python3
"""בדיקה חיה מול Gemini: מה קורה כשמכבים את החיתוך השקט.

למה הסקריפט הזה קיים
--------------------
``services/chunking_service.py`` מגביל כל צ'אנק בתקציב בייטים, כדי שלא
נחצה את תקרת הקלט של ``gemini-embedding-001`` (2,048 טוקנים). מעל התקרה
המודל **חותך בשקט**: אין שגיאה, אין אזהרה, והווקטור החוזר מתאר רק את
תחילת הקלט.

``EmbedContentConfig.autoTruncate`` אמור לכבות את ההתנהגות הזו
(מקור: https://ai.google.dev/api/embeddings — "Whether to silently truncate
the input content if it's longer than the maximum sequence length").
מה שלא אימתנו הוא **מה בדיוק Gemini Developer API מחזיר** כשהשדה נשלח
ובקלט יש חריגה: התיעוד של Vertex אומר שהבקשה נכשלת, ולתיעוד של
Gemini API אין משפט מקביל.

לכן ``EMBEDDING_AUTO_TRUNCATE`` ברירת מחדל ``true`` (ההתנהגות הקיימת),
והסקריפט הזה הוא מה שמאפשר להפוך אותה. הוא **קורא בלבד** — לא נוגע ב-DB
ולא כותב שום דבר.

הרצה::

    GEMINI_API_KEY=... python scripts/probe_embedding_limits.py

מה לחפש בפלט:

* ``short + autoTruncate:false`` → 200. אם לא — השדה נדחה, ואסור להפוך
  את ברירת המחדל: כל קריאה תיכשל והחיפוש הסמנטי כולו ייפול לחיפוש טקסט.
* ``long  + autoTruncate:false`` → 4xx. זו הראיה שהחיתוך השקט אכן כובה.
* ``long  + autoTruncate:true``  → 200 (וזה בדיוק החיתוך השקט שבעטיו
  נפתח האישו).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _resolve_target() -> tuple:
    """מודל, גרסת API ומימדים — **מאותו מקור שממנו ה-worker לוקח אותם**.

    פרוב שבודק ``gemini-embedding-001`` בזמן שהקונפיג ב-DB מצביע על מודל אחר
    היה יכול לעבור בזמן שהמסלול האמיתי נכשל. ``get_embedding_settings_cached``
    קורא את ``system_config`` ונופל ל-ENV כשאין DB — בדיוק כמו בייצור.

    הנרמול אינו קוסמטי: ``GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001``
    היה בונה ``.../models/models/gemini-embedding-001:embedContent``, וכל
    שלושת הפרובים היו נכשלים ב-404 במקום לבדוק את מגבלת הקלט.
    """
    from services.semantic_embedding_settings import (  # noqa: E402
        get_embedding_settings_cached,
        normalize_model_name,
    )

    settings = None
    try:
        settings = get_embedding_settings_cached(allow_db=True)
    except Exception:
        settings = None

    model = normalize_model_name(
        (getattr(settings, "model", "") or "")
        or os.getenv("GEMINI_EMBEDDING_MODEL", "")
        or "gemini-embedding-001"
    )

    api_version = str(
        (getattr(settings, "api_version", "") or "")
        or os.getenv("GEMINI_API_VERSION", "")
        or "v1beta"
    ).strip().strip("/")
    if api_version not in {"v1", "v1beta"}:
        # אותו כלל כמו ב-``EmbeddingService._base_url``.
        api_version = "v1beta"

    try:
        dimensions = int(getattr(settings, "dimensions", 0) or 0) or int(
            os.getenv("EMBEDDING_DIMENSIONS", "768") or 768
        )
    except (TypeError, ValueError):
        dimensions = 768

    return model, api_version, dimensions


DEFAULT_MODEL, DEFAULT_API_VERSION, DEFAULT_DIMENSIONS = _resolve_target()

# ~2,048 טוקנים הם בערך 7,000-8,000 בייט באנגלית. 40,000 תווים חורגים
# בבירור, בלי להיות כה גדולים שהבקשה תידחה מסיבה אחרת.
LONG_TEXT = "def handle_request(payload):\n    return payload\n" * 850
SHORT_TEXT = "def handle_request(payload):\n    return payload\n"


def _probe(client: httpx.Client, *, text: str, auto_truncate: bool, label: str) -> int:
    """מריץ פרוב אחד ומחזיר את קוד הסטטוס (``0`` = לא הגיע לשרת)."""
    url = (
        f"https://generativelanguage.googleapis.com/{DEFAULT_API_VERSION}"
        f"/models/{DEFAULT_MODEL}:embedContent"
    )
    payload = {
        "model": f"models/{DEFAULT_MODEL}",
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": DEFAULT_DIMENSIONS,
    }
    if not auto_truncate:
        payload["embedContentConfig"] = {"autoTruncate": False}

    try:
        response = client.post(url, json=payload)
    except Exception as exc:
        print(f"{label:34s} -> transport error: {exc}")
        return 0
    body = response.text or ""
    dims = ""
    if response.status_code == 200:
        try:
            values = response.json()["embedding"]["values"]
            dims = f" dims={len(values)}"
        except Exception:
            dims = " (200 but no embedding values)"

    print(f"{label:34s} bytes={len(text.encode('utf-8')):6d} -> HTTP {response.status_code}{dims}")
    if response.status_code != 200:
        try:
            message = json.loads(body).get("error", {}).get("message", "")
        except Exception:
            message = body[:400]
        print(f"    error: {message[:400]}")
    return int(response.status_code)


def main() -> int:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("GEMINI_API_KEY is not set - nothing to probe.", file=sys.stderr)
        return 2

    # המפתח יושב בכותרת ולא בשורת השאילתה, בדיוק כמו ב-EmbeddingService:
    # אינטגרציית ה-HTTP של Sentry מתעדת את ה-query string בעצמה.
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    print(f"model={DEFAULT_MODEL} api={DEFAULT_API_VERSION} dims={DEFAULT_DIMENSIONS}\n")

    with httpx.Client(timeout=60.0, headers=headers) as client:
        short_off = _probe(
            client, text=SHORT_TEXT, auto_truncate=False, label="short + autoTruncate:false"
        )
        long_off = _probe(
            client, text=LONG_TEXT, auto_truncate=False, label="long  + autoTruncate:false"
        )
        long_on = _probe(
            client, text=LONG_TEXT, auto_truncate=True, label="long  + autoTruncate:true"
        )

    print()
    if short_off != 200:
        print(
            "VERDICT: the API rejected embedContentConfig.autoTruncate itself. "
            "Do NOT set EMBEDDING_AUTO_TRUNCATE=false - every call would fail."
        )
        return 1
    if long_off == 200:
        print(
            "VERDICT: autoTruncate:false did NOT stop the silent truncation "
            f"(oversized input still returned 200; autoTruncate:true returned {long_on}). "
            "The byte budget in services/chunking_service.py remains the only real guard."
        )
        return 1
    print(
        f"VERDICT: autoTruncate:false turns oversized input into HTTP {long_off} "
        f"(with autoTruncate:true it returned {long_on}). "
        "EMBEDDING_AUTO_TRUNCATE=false is safe to enable."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
