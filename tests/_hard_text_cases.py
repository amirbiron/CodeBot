"""12 המקרים הקשים של טקסט — מקור אחד לכל טסט שבודק שבתים עוברים בלי שינוי.

BOM, ‏CR בודד, תווי כיווניות, ZWJ, ‏U+2028, ‏NEL/DEL, ‏NUL, ירידות שורה בסוף, escape כטקסט
ותווים של ארבעה בתים. המטריצה נבנתה ל-``tests/test_mcp_content_sha256_real_mongo.py``
(הדרך דרך BSON והדרייבר), וראוט ההורדה (``tests/test_mcp_downloads.py``) מריץ עליה את
הלולאה הסגורה העלאה ← שמירה ← הורדה. במקום אחד, כי שתי רשימות של "המקרים הקשים" היו
נסחפות זו מזו: מקרה שנוסף לאחת היה נבדק רק בה.

קבועים ולא fixtures, כמו ``_save_layer_harness.py`` (T3).
"""

from __future__ import annotations

CASES = {
    "bom_crlf": "\ufeffline one\r\nline two\r\n",
    "lone_cr": "a\rb\n",
    "rlm_lrm": "גרסה\u200f 2.0\u200e\n",
    "rlo_trojan": "x = '\u202eabc\u202c'\n",
    "zwj_family": "\U0001F468\u200d\U0001F469\u200d\U0001F467\n",
    "line_sep": "a\u2028b\u2029c\n",
    "nel_del": "a\u0085b\x7fc\n",
    "nul": "a\x00b\n",
    "trailing_newlines": "x = 1\n\n\n",
    "no_trailing_newline": "x = 1",
    "escape_text": 'RLM = "\\u200f"\n',
    "hebrew_4byte_mix": "שלום \U0001F600 \U00010348 world\n",
}
