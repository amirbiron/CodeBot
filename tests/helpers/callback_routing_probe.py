"""עוזר לטסט: מעביר לחיצות על כפתורים דרך ``Application.process_update`` של python-telegram-bot האמיתי, בתת-תהליך,
ורושם כמה פעמים כל לחיצה נכנסה ל-``AdvancedBotHandlers.handle_callback_query``.

הטסט שמריץ אותו: ``tests/test_callback_routing_real_ptb.py``.

**למה תת-תהליך.** ``tests/conftest.py`` מחליף את ``telegram`` ב-stubs בכל הסוויטה, ומה שנבדק כאן — איזה handler בכל
קבוצה תופס את העדכון, ושהעיבוד ממשיך לקבוצה הבאה — חי בקוד של PTB שאין ב-stubs. כמו ``advisor_routing_probe.py``.

**התרחישים.**

- ``app``: ה-``Application`` ש-``CodeKeeperBot`` בונה ב-``main.py``, עם כל ה-handlers בסדר ובקבוצות של הפרודקשן. לפני כל
  לחיצה הגולש "במצב חיפוש" (``awaiting_search_text``), כדי לראות שה-catch-all של ``conversation_handlers`` בקבוצה 5 עדיין
  מקבל את הלחיצה: הוא זה שמוציא ממצב חיפוש בכל לחיצה על כפתור אחר.
- ``alone``: אפליקציה ש-``AdvancedBotHandlers`` לבדו נרשם בה, בלי ה-catch-all של ``conversation_handlers`` שתופס היום את
  קבוצה 5 לפניו. כך נבדק שהטיפול היחיד לא נשען על סדר הרישום מול מודול אחר.

**מה מדומה.** טלגרם (``fake_bot_api.py``), ו-``AdvancedBotHandlers.handle_callback_query`` — רשם שסופר כניסות, בלי מסד
ובלי יצירת תמונות. ה-catch-all של ``conversation_handlers`` אמיתי.

**הפלט** הוא קובץ JSON: לכל לחיצה, כמה פעמים היא נכנסה ל-``handle_callback_query``, והאם הגולש יצא ממצב החיפוש.

שימוש: ``python -B callback_routing_probe.py <result.json> <app|alone>``
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback

from fake_bot_api import BOT_USER, FakeBotApi, point_application_builder_at

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: תקרה לריצה כולה, כולל הייבוא של ``main``. אם משהו נתקע, הטסט מקבל דוח עם ``outcome: deadline``.
DEADLINE_SECONDS = 60.0

#: לחיצות שה-handlers המוקדמים של ``AdvancedBotHandlers`` (קבוצה ‎-5) תופסים — כל אחת חייבת להיכנס פעם אחת בדיוק.
EARLY_ROUTED = [
    "img_download:-:a.py",
    "img_drive:-:a.py",
    "save_to_drive_a.py",
    "regenerate_image_a.py",
    "edit_image_settings_a.py",
    "img_set_theme:dark:a.py",
    "img_settings_done:a.py",
    "img_section:hq",
    "fav_toggle_id:abc",
    "share_gist_a.py",
    "cancel_share",
]

#: שיתוף לפי ObjectId — של ``conversation_handlers``, לא של ``AdvancedBotHandlers``.
SHARE_BY_ID = ["share_gist_id:65a1b2c3d4e5f60718293a4b", "share_pastebin_id:65a1b2c3d4e5f60718293a4b"]

#: קידומת שאף handler מוקדם לא תופס — מגיעה ל-catch-all של ``AdvancedBotHandlers`` כשאין catch-all אחר לפניו.
NOT_EARLY = ["highlight_a.py"]


def _click(update_id: int, user_id: int, data: str) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cq{update_id}",
            "from": {"id": user_id, "is_bot": False, "first_name": "Probe"},
            "chat_instance": "probe",
            "data": data,
            "message": {
                "message_id": 10,
                "date": int(time.time()),
                "chat": {"id": user_id, "type": "private"},
                "from": BOT_USER,
                "text": "x",
            },
        },
    }


async def _run(scenario: str, report: dict, api: FakeBotApi) -> None:
    base_url = api.start()
    sys.path.insert(0, REPO_ROOT)
    point_application_builder_at(base_url)

    from telegram import Update
    from telegram.ext import ApplicationBuilder

    import bot_handlers

    entered: list[str] = []

    async def record(self, update, context) -> None:
        entered.append(update.callback_query.data)

    # לפני שהמחלקה נבנית: ה-handlers נרשמים עם המתודה הקשורה, ולכן החלפה אחרי הבנייה לא הייתה נספרת
    bot_handlers.AdvancedBotHandlers.handle_callback_query = record

    if scenario == "app":
        import main as bot_main

        app = bot_main.CodeKeeperBot().application
        clicks = EARLY_ROUTED + SHARE_BY_ID
    elif scenario == "alone":
        app = ApplicationBuilder().token("0:probe").build()
        bot_handlers.AdvancedBotHandlers(app)
        clicks = EARLY_ROUTED + NOT_EARLY
    else:
        raise ValueError(scenario)

    report["groups"] = {str(group): [type(h).__name__ for h in handlers] for group, handlers in sorted(app.handlers.items())}
    await app.initialize()
    results = []
    try:
        for index, data in enumerate(clicks):
            # גולש אחר לכל לחיצה: שער מגבלת הקצב וה-guard של לחיצות כפולות סופרים לפי גולש, והם אינם הנושא כאן
            user_id = 2000 + index
            app.user_data[user_id]["awaiting_search_text"] = True
            before = len(entered)
            await app.process_update(Update.de_json(_click(100 + index, user_id, data), app.bot))
            results.append({
                "data": data,
                "advanced_calls": len(entered) - before,
                "left_search_mode": "awaiting_search_text" not in app.user_data[user_id],
            })
    finally:
        report["clicks"] = results
        await app.shutdown()


def main() -> int:
    result_path, scenario = sys.argv[1], sys.argv[2]
    report: dict = {"scenario": scenario, "outcome": None}
    api = FakeBotApi()

    def write_report() -> None:
        report["fake_server_errors"] = list(api.server_errors)
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False)

    def on_deadline() -> None:
        report["outcome"] = "deadline"
        write_report()
        os._exit(3)

    watchdog = threading.Timer(DEADLINE_SECONDS, on_deadline)
    watchdog.daemon = True
    watchdog.start()
    try:
        asyncio.run(_run(scenario, report, api))
        report["outcome"] = "done"
    except BaseException:  # noqa: BLE001 - הפרוב מדווח כל מה שעלה, והטסט מחליט
        report["outcome"] = "raised"
        report["traceback"] = traceback.format_exc()[-4000:]
    write_report()
    # בלי לחכות לחוטים שהבוט השאיר (ג'ובים, לקוחות מסד): הם אינם הנושא כאן, והדוח כבר נכתב
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
