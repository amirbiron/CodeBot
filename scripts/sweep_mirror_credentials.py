#!/usr/bin/env python3
"""ניקוי טוקני GitHub מה-``remote.origin.url`` של כל המראות בדיסק של השירות (#3480).

``scripts/start_webapp.sh`` מריץ אותו בעליית הוובאפ, ברקע ואחרי ש-Gunicorn כבר
עלה. בשירות ה-MCP אותו ניקוי רץ מתוך ``create_app`` (``start_credential_sweep``).
העבודה עצמה ב-``services.git_mirror_service.sweep_stored_credentials``; כאן רק
נקודת כניסה, שמדפיסה את שורת הלוג ``mirror credential sweep: ...`` לפלט של השירות.

קוד יציאה: 0 כשאין כשלים (כולל "אין תיקיית מראות"), 1 כשמראה אחת לפחות לא נוקתה.
"""

from __future__ import annotations

import logging
import os
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(name)s: %(message)s")
    # Make the repo importable when run directly.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from services.git_mirror_service import sweep_stored_credentials  # noqa: E402

    stats = sweep_stored_credentials()
    if stats is None:
        return 0
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
