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

אחרי שלושת אלה רץ גם החלק של ``batchEmbedContents``, שהלקוח הסינכרוני
(``SyncEmbeddingClient`` ב-``services/embedding_service.py``) נשען עליו:

* ``outputDimensionality`` ברמה העליונה של הבקשה מול בתוך ``embedContentConfig`` —
  כמה מימדים חוזרים בכל אחד. מה שנמדד ב-7.10.2026: 768 ברמה העליונה, ו-3,072 בתוך
  הבלוק, כלומר שם הוא נבלע.
* אצווה בגודל ``GEMINI_MAX_BATCH_REQUESTS`` ובגודל אחד יותר — מה התקרה בפועל.
* ``countTokens`` על הקלט הגדול ביותר שכל מסלול הטמעה שולח (``_largest_inputs``), בכמה סוגי
  תוכן צפוף: נתח של התיעוד, ששביל הכותרות כבר כלול בו, והטקסט של סניפט — נתח ועוד מטא-דאטה
  ומפריד (``create_embedding_text``), כלומר גדול מתקציב הנתח. שורה שעוברת את
  ``INPUT_TOKEN_LIMIT`` מסומנת. מה שנמדד ב-7.10.2026:

  - **תיעוד:** הצפוף ביותר הוא ספרות ונתיב SVG — 1,949 טוקנים ל-1,966 בתים, כמעט טוקן לכל
    בית. כל הסוגים מתחת לתקרה, במרווח קטן שנשען על הנחה שלא מצאתי לה מקור כתוב של Google:
    שאין יותר מטוקן אחד לכל בית.
  - **סניפטים:** ספרות, סימנים ונתיב SVG מדולגים (``is_low_information_chunk``), אבל hex
    ורשימת UUID עוברים את הסינון, והקלט האפקטיבי שלהם (2,451 בתים) מגיע ל-2,152 ול-2,129
    טוקנים — **מעל התקרה**. ``autoTruncate: false`` לא עוצר את זה (הבלוק נבלע, למעלה), ולכן
    Gemini חותך בשקט את סוף הנתח. זה המסלול של ה-worker של הסניפטים, מלפני אינדקס התיעוד, וה-
    docstring של ``create_embedding_text`` מתעד בו פער רק לתוכן צפוף-סימנים.
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
    # הנרמול נלקח מ-``semantic_embedding_settings`` ולא נכתב כאן מחדש: עותק
    # שני היה יכול להסכים היום ולהיפרד מחר, והפרוב היה בודק endpoint אחר
    # מזה שה-worker פונה אליו — כלומר תשובה שאינה רלוונטית להחלטה שהוא אמור
    # להכריע. ``_normalize_api_version`` היא אותה פונקציה ש-``EmbeddingSettings``
    # משתמשת בה.
    from services.semantic_embedding_settings import (  # noqa: E402
        _normalize_api_version,
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

    api_version = _normalize_api_version(
        (getattr(settings, "api_version", "") or "") or os.getenv("GEMINI_API_VERSION", "")
    )

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

# תקרת הקלט של ``gemini-embedding-001``: "Input token limit 2,048"
# (https://ai.google.dev/gemini-api/docs/embeddings). מה שמעליה נחתך בשקט — ראו את הפסקה על
# ``autoTruncate`` למעלה.
INPUT_TOKEN_LIMIT = 2048


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


def _batch_dims(client: httpx.Client, requests: list) -> str:
    """שולח ``batchEmbedContents`` ומחזיר תיאור קצר: מספר המימדים, או הקוד וההודעה."""
    url = (
        f"https://generativelanguage.googleapis.com/{DEFAULT_API_VERSION}"
        f"/models/{DEFAULT_MODEL}:batchEmbedContents"
    )
    try:
        response = client.post(url, json={"requests": requests})
    except Exception as exc:
        return f"transport error: {type(exc).__name__}"
    if response.status_code != 200:
        try:
            message = json.loads(response.text).get("error", {}).get("message", "")
        except Exception:
            message = ""
        return f"HTTP {response.status_code}: {str(message).strip()[:200]}"
    try:
        embeddings = response.json()["embeddings"]
        return f"HTTP 200, {len(embeddings)} vectors, dims={sorted({len(e['values']) for e in embeddings})}"
    except Exception:
        return "HTTP 200 but no embeddings"


def _probe_batch_contract(client: httpx.Client) -> None:
    """מה ש-``SyncEmbeddingClient`` נשען עליו: איפה המימד נאכף, ומה תקרת האצווה והטוקנים.

    הבקשה "הנכונה" נבנית ב-``build_embed_content_request`` — אותה פונקציה שהלקוחות משתמשים
    בה — כדי שהפרוב יבדוק את מה שבאמת נשלח, ולא עותק שלו.
    """
    import random

    from services.embedding_service import (  # noqa: E402
        GEMINI_MAX_BATCH_REQUESTS,
        build_embed_content_request,
    )

    def shaped(text: str) -> dict:
        return build_embed_content_request(text, model=DEFAULT_MODEL, dimensions=DEFAULT_DIMENSIONS)

    in_config = {
        "model": f"models/{DEFAULT_MODEL}",
        "content": {"parts": [{"text": SHORT_TEXT}]},
        "embedContentConfig": {"outputDimensionality": DEFAULT_DIMENSIONS},
    }
    print(f"{'batch, dims at the top (as sent)':34s} -> {_batch_dims(client, [shaped(SHORT_TEXT)])}")
    print(f"{'batch, dims inside embedContentConfig':34s} -> {_batch_dims(client, [in_config])}")
    for size in (GEMINI_MAX_BATCH_REQUESTS, GEMINI_MAX_BATCH_REQUESTS + 1):
        requests = [shaped(f"t{i}") for i in range(size)]
        print(f"{f'batch of {size}':34s} -> {_batch_dims(client, requests)}")

    # ``chunking_service`` טוען את קונפיג האפליקציה (``config.py``), ולכן החלק הזה דורש את
    # משתני הסביבה שלה (``BOT_TOKEN``, ``MONGODB_URL``). הוא רץ אחרון, כך שבלעדיהם החלקים
    # שלמעלה כבר הודפסו לפני שהשגיאה עולה.
    url = (
        f"https://generativelanguage.googleapis.com/{DEFAULT_API_VERSION}"
        f"/models/{DEFAULT_MODEL}:countTokens"
    )
    print(f"countTokens on the largest input each embedding path sends (input limit {INPUT_TOKEN_LIMIT:,}):")
    for path, kind, text in _largest_inputs(random.Random(7)):
        label = f"  {path:13s} {kind:12s}"
        if text is None:
            print(f"{label} -> dropped by is_low_information_chunk, never sent")
            continue
        try:
            response = client.post(url, json={"contents": [{"parts": [{"text": text}]}]})
        except Exception as exc:
            print(f"{label} -> transport error: {type(exc).__name__}")
            continue
        try:
            body = response.json()
        except ValueError:
            body = None
        tokens = body.get("totalTokens") if response.status_code == 200 and isinstance(body, dict) else None
        over = " <- OVER the limit: Gemini cuts the tail silently" if (
            isinstance(tokens, int) and tokens > INPUT_TOKEN_LIMIT
        ) else ""
        print(f"{label} bytes={len(text.encode('utf-8')):5d} -> HTTP {response.status_code}, "
              f"totalTokens={tokens}{over}")


#: סוגי תוכן צפוף — מה שמכניס הכי הרבה טוקנים לכל בית. ``dense code`` הוא שתי אותיות על כל שבעה
#: סימנים או ספרות: היחס 7/9 נמוך מ-``LOW_INFORMATION_RATIO``, כך שנתח כזה **עובר** את הסינון של
#: הסניפטים. גם ``hex`` ו-``uuid list`` עוברים אותו, כי הסינון סופר רק ספרות וסימנים, והאותיות
#: a–f אינן כאלה. ספרות, סימנים ונתיב SVG נשלחים רק במסלול של התיעוד, שאין בו סינון כזה.
DENSE_KINDS = ("punctuation", "digits", "svg path", "dense code", "hex", "uuid list")


def _dense_line(kind: str, rng) -> str:
    """שורה אחת של 80 תווים מהסוג ``kind``."""
    import string

    if kind == "punctuation":
        return "".join(rng.choice(string.punctuation) for _ in range(80))
    if kind == "digits":
        line = ""
        while len(line) < 80:
            line += f"{rng.randint(0, 9999)}.{rng.randint(0, 99):02d}, "
        return line[:80]
    if kind == "svg path":
        line = ""
        while len(line) < 80:
            x, y = rng.randint(0, 9999), rng.randint(0, 9999)
            line += f"{rng.choice('MLCQ')}{x // 10}.{x % 10},{y // 10}.{y % 10}"
        return line[:80]
    if kind == "hex":
        return "".join(rng.choice("0123456789abcdef") for _ in range(80))
    if kind == "uuid list":
        line = ""
        while len(line) < 80:
            h = "".join(rng.choice("0123456789abcdef") for _ in range(32))
            line += f'"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}", '
        return line[:80]
    if kind == "dense code":
        line = ""
        while len(line) < 80:
            unit = [rng.choice(string.ascii_letters) for _ in range(2)]
            unit += [rng.choice(string.digits + string.punctuation) for _ in range(7)]
            rng.shuffle(unit)
            line += "".join(unit)
        return line[:80]
    raise ValueError(f"unknown dense kind {kind!r}")


def _largest_inputs(rng) -> list[tuple[str, str, str | None]]:
    """הקלט הגדול ביותר שכל מסלול הטמעה שולח, לכל סוג תוכן — **נבנה בפונקציות שבונות אותו בייצור**,
    כדי למדוד את מה שבאמת נשלח ולא את תקציב הבתים לבדו:

    * **תיעוד** (``SyncEmbeddingClient``, מעבר האינדוקס): הנתח עצמו, ששביל הכותרות כבר כלול בו, עד
      ``CHUNK_MAX_BYTES`` (``_chunk_texts`` ב-``services/docs_index_service.py``).
    * **סניפט** (``EmbeddingService``, ה-worker): לנתח של ``split_code_to_chunks`` מתווספים מטא-דאטה
      ומפריד (``create_embedding_text``), כך שהקלט האפקטיבי גדול מהנתח. המטא-דאטה כאן ממלאת את
      ``EMBEDDING_METADATA_MAX_BYTES``. נתח שה-worker מדלג עליו (``is_low_information_chunk``) חוזר
      עם ``None``.
    """
    from services.chunking_service import (  # noqa: E402
        create_embedding_text,
        is_low_information_chunk,
        split_code_to_chunks,
    )
    from services.docs_index_service import _chunk_texts  # noqa: E402

    inputs: list[tuple[str, str, str | None]] = []
    for kind in DENSE_KINDS:
        body = "\n".join(_dense_line(kind, rng) for _ in range(100))
        docs_text = max(_chunk_texts(("עמוד", "סעיף"), body), key=lambda text: len(text.encode("utf-8")))
        inputs.append(("docs chunk", kind, docs_text))
    for kind in DENSE_KINDS:
        body = "\n".join(_dense_line(kind, rng) for _ in range(100))
        chunk = max((part.content for part in split_code_to_chunks(body)), key=lambda text: len(text.encode("utf-8")))
        if is_low_information_chunk(chunk):
            inputs.append(("snippet text", kind, None))
            continue
        snippet_text = create_embedding_text(
            code_chunk=chunk,
            title="bundle.min.js",
            description=body[:1000],
            tags=["minified", "generated"],
            language="javascript",
        )
        inputs.append(("snippet text", kind, snippet_text))
    return inputs


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
        _probe_batch_contract(client)

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
