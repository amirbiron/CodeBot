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

DEFAULT_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
DEFAULT_API_VERSION = os.getenv("GEMINI_API_VERSION", "v1beta")
DEFAULT_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768") or 768)

# ~2,048 טוקנים הם בערך 7,000-8,000 בייט באנגלית. 40,000 תווים חורגים
# בבירור, בלי להיות כה גדולים שהבקשה תידחה מסיבה אחרת.
LONG_TEXT = "def handle_request(payload):\n    return payload\n" * 850
SHORT_TEXT = "def handle_request(payload):\n    return payload\n"


def _probe(client: httpx.Client, *, text: str, auto_truncate: bool, label: str) -> None:
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

    response = client.post(url, json=payload)
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
        _probe(client, text=SHORT_TEXT, auto_truncate=False, label="short + autoTruncate:false")
        _probe(client, text=LONG_TEXT, auto_truncate=False, label="long  + autoTruncate:false")
        _probe(client, text=LONG_TEXT, auto_truncate=True, label="long  + autoTruncate:true")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
