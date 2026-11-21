"""הקשר הלוגים וה-scope של Sentry בבוט: לכל עדכון, ולכל ריצה של ג'וב, הקשר משלו.

ההקשר (``request_id``, ``user_id``, ``chat_id``, ``command`` ב-structlog, והתגיות שלהם ב-Sentry) דלף בבוט בשני כיוונים:
מעדכון לעדכון שאחריו, ומעדכון אחד לכל הג'ובים בתהליך — עד העדכון הבא שתזמן ג'וב. ההסבר המלא של המנגנון ב-docstring של
``observability.isolated_observability_scope``, וההיסטוריה ב-``docs/whats-new/2026-11.rst``, 2026-11-20.

המודול מחבר את הבלוק הזה לשתי הנקודות שכל יחידת עבודה של הבוט עוברת בהן. שתיהן נכנסות דרך ``ApplicationBuilder`` ב-
``main.py``:

- **עדכון** — :class:`IsolatedUpdateApplication` דורס את ``Application.process_update`` (``.application_class(...)``). ב-
  python-telegram-bot 22.5 ``Application.__process_update_wrapper`` קורא ל-``self.process_update(update)``, ולכן כל עדכון
  עובר שם. תת-מחלקה ולא עטיפה על המופע: ל-``Application`` יש ``__slots__`` בלי ``__dict__``, והשמה של ``process_update``
  על מופע נכשלת ב-``AttributeError: ... is read-only``. ``request_id`` חדש נוצר לכל עדכון: "מזהה מתואם לבקשה/פעולה"
  (``docs/observability/guidelines.md``).
- **ג'וב** — :class:`IsolatedJobQueue` דורס את ``JobQueue.job_callback`` (``.job_queue(...)``). כל ``run_*`` של PTB 22.5 רושם
  ב-APScheduler את ``self.job_callback``, ולכן כל ג'וב — גם ``run_once`` מתוך handler — עובר שם.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from telegram import Update
from telegram.ext import Application, JobQueue

logger = logging.getLogger(__name__)

# ``main.py`` ממשיך לעבוד כש-``observability`` לא נטען (``_observability = None`` ופונקציות ריקות), ו"מערכת observability
# לעולם לא מפילה את היישום" (עקרון Fail-Open ב-``docs/observability/guidelines.md``). המודול הזה נטען מ-``main.py`` בעלייה,
# ולכן אותה החלטה, פעם אחת, כאן: בלי ``observability`` עדכונים וג'ובים רצים בלי הקשר מבודד. גבול של עלייה, ולכן ``Exception``
# כמו ב-``main.py`` — עם traceback מלא, ולמצב משלו ("אין observability"), לא לשום מצב של סיכון אחר.
try:
    import observability as _observability_at_import
except Exception:
    logger.exception("observability failed to import; bot updates and jobs run without an isolated logging scope")
    _observability_at_import = None


def _observability() -> Any:
    """המודול ``observability`` כפי שהוא ב-``sys.modules`` בזמן הקריאה, או ``None`` כשהייבוא שלו נכשל בעלייה.

    ``sys.modules`` ולא ההפניה מהייבוא: טסטים מחליפים את ``observability`` ב-``sys.modules`` בדמה חלקית לפני
    ``import main`` (למשל ``tests/test_backups_cleanup_disabled_by_default.py``), והפניה שנשמרת בייבוא הייתה נשארת על
    הדמה גם אחרי שהטסט מחזיר את המודול האמיתי. ייבוא שנכשל לא נשאר ב-``sys.modules``, ולכן אז חוזר ``None`` — בלי ניסיון
    ייבוא חוזר בכל עדכון.
    """
    return sys.modules.get("observability", _observability_at_import)


#: התחילית של ``command`` בעדכון, כמו ``webapp:`` בוובאפ (``webapp/app.py``).
UPDATE_COMMAND_PREFIX = "bot:"
#: התחילית של ``command`` בריצה של ג'וב.
JOB_COMMAND_PREFIX = "job:"


def update_command_name(update: object) -> str:
    """שם הפקודה של העדכון, בלי ``/``, בלי ``@bot`` ובאותיות קטנות — או ``""`` כשאין.

    הודעה שהמילה הראשונה שלה מתחילה ב-``/``; אחרת המילה הראשונה ב-``data`` של callback; אחרת ``inline_query`` לשאילתה
    בשורה. אותה גזירה ש-``_pre_update`` ב-``main.py`` עשה עד 20.11.2026, והוא קורא לפונקציה הזו עכשיו בשביל
    ``context.user_data``.
    """
    if not isinstance(update, Update):
        return ""
    command_name = ""
    message = update.effective_message
    if message is not None and isinstance(message.text, str):
        parts = message.text.split()
        if parts and parts[0].startswith("/"):
            command_name = parts[0]
    if not command_name:
        callback = update.callback_query
        if callback is not None and isinstance(callback.data, str):
            parts = callback.data.split()
            if parts:
                command_name = parts[0]
    if not command_name and update.inline_query is not None:
        command_name = "inline_query"
    cleaned = command_name.strip()
    if cleaned.startswith("/"):
        cleaned = cleaned[1:]
    if "@" in cleaned:
        cleaned = cleaned.split("@", 1)[0]
    return cleaned.lower()


def bind_update_context(observability: Any, update: object) -> None:
    """כורך את ההקשר של עדכון: ``request_id`` חדש, המשתמש והצ'אט (מטושטשים ב-``bind_user_context``), והפקודה אם יש."""
    observability.bind_request_id(observability.generate_request_id())
    if not isinstance(update, Update):
        return
    user = update.effective_user
    chat = update.effective_chat
    observability.bind_user_context(
        user_id=user.id if user is not None else None,
        chat_id=chat.id if chat is not None else None,
    )
    command = update_command_name(update)
    if command:
        observability.bind_command(f"{UPDATE_COMMAND_PREFIX}{command}")


class IsolatedUpdateApplication(Application):
    """``Application`` שכל עדכון בו רץ ב-``isolated_observability_scope``, עם ההקשר שלו כרוך לפני כל ה-handlers.

    ``__slots__`` ריק כמו במחלקת הבסיס: בלעדיו למופע היה ``__dict__``, ומאפיינים ש-``main.py`` מנסה היום לשים על
    האפליקציה ונכשלים — למשל ``_codebot_tracing_installed`` ב-``_install_tracing_layer`` — היו מתחילים לעבוד בלי שאיש
    החליט על כך.
    """

    __slots__ = ()

    async def process_update(self, update: object) -> None:
        observability = _observability()
        if observability is None:
            # ``observability`` לא נטען (נרשם בעלייה): העדכון מטופל בלי הקשר מבודד, ולא נכשל בגללו.
            await super().process_update(update)
            return
        with observability.isolated_observability_scope():
            bind_update_context(observability, update)
            await super().process_update(update)


def _job_callback_name(job: Any) -> str:
    """שם הפונקציה של הג'וב — ולא ``job.name``: שמות כמו ``drive_<user_id>`` (``handlers/drive/menu.py``) נושאים מזהה
    משתמש גלוי, ו-``command`` נכנס לכל שורת לוג ולתגית ב-Sentry. מזהה המשתמש של ג'וב עובר דרך ``bind_user_context``,
    מטושטש."""
    callback = job.callback
    return getattr(callback, "__name__", None) or type(callback).__name__


def bind_job_context(observability: Any, job: Any) -> None:
    """כורך את ההקשר של ריצת ג'וב: ``request_id`` משלה, ``command=job:<שם הפונקציה>``, והמשתמש והצ'אט שהג'וב תוזמן
    עבורם (``chat_id``/``user_id`` של ``run_once`` וחבריו) — ולא מי שבמקרה תזמן ג'וב אחרון."""
    observability.bind_request_id(observability.generate_request_id())
    observability.bind_command(f"{JOB_COMMAND_PREFIX}{_job_callback_name(job)}")
    observability.bind_user_context(user_id=job.user_id, chat_id=job.chat_id)


class IsolatedJobQueue(JobQueue):
    """``JobQueue`` שכל ריצה של ג'וב בו מתחילה בהקשר משלה (``isolated_observability_scope`` + :func:`bind_job_context`).

    בלעדיו, ג'וב יורש את ההקשר שבו APScheduler נקרא לאחרונה — ראו את הסעיף על הג'ובים ב-docstring של
    ``observability.isolated_observability_scope``. נכנס לאפליקציה דרך ``ApplicationBuilder.job_queue`` ב-``main.py``.
    """

    @staticmethod
    async def job_callback(job_queue: Any, job: Any) -> None:
        observability = _observability()
        if observability is None:
            # כמו ב-``IsolatedUpdateApplication.process_update``: בלי ``observability`` הג'וב רץ בלי הקשר מבודד.
            await JobQueue.job_callback(job_queue, job)
            return
        with observability.isolated_observability_scope():
            bind_job_context(observability, job)
            await JobQueue.job_callback(job_queue, job)
