"""התאמת תשובה לתקציב: לחתוך במקום שיש בו סימן, או לסרב בצורה אחת (#3460, ריוויו Han על #3492).

``answer_size`` אומר **כמה** — התקציב, והמדידה כפי שהתשובה נשלחת. המודול הזה אומר **מה
עושים** כשתשובה אינה נכנסת, ובמקום אחד לכל הכלים:

* :func:`too_large` — **הליבה של כל סירוב** ``answer_too_large``: ``error``, ``bytes``
  ו-``max``. עד הריוויו כל אחד משבעת המקומות שסירבו איית אותה ביד, בשלושה שמות לאותו
  קבוע; כל מקום ממשיך לשים סביבה את ההקשר שלו, בסדר שהיה לו.
* :func:`cut` — הסיבה ``byte_budget`` של חיתוך. הסיבה היא המילה של ``answer_size``;
  מה שנוסף כאן הוא הרישום (למטה).
* :func:`fit_line_range` — טווח שורות שנגמר מוקדם על גבול שורה (עבר מ-``handlers``).
* :func:`fit_lists` ו-:func:`fit_refusal` — רשימות שמוותרות על הסוף שלהן עם דגל, ומחרוזת
  בהקשר שיורדת שלמה עם הגודל שלה (עברו מ-``docs_handlers``).

**למה מודול משלו, מעל ``answer_size`` ומתחת לכל השאר.** ``fit_line_range`` ישב ב-
``handlers`` — מודול הארגומנטים והעריכה — ו-``fit_refusal`` ב-``docs_handlers``, ולכן
``backend`` ו-``repo_handlers`` משכו מודול שלם בשביל פונקציה אחת, ושתי שגרות "להתאים או
לסרב" של קריאת קובץ נכתבו פעמיים והתפצלו: רק הקובץ השמור עבר ``fit_refusal``. כאן אין
תלות בשום מודול של החבילה מלבד ``answer_size``, כך שכל אחד מהם יכול לייבא ממנו.

**הרישום — מה שנחתך או סורב בקריאה אחת.** ``AdminAwareFastMCP.call_tool`` פותח
:func:`recording` סביב גוף הכלי, ו-:func:`too_large` ו-:func:`cut` כותבים לתוכו; בסוף
הקריאה נכתבת שורת ``answer_size_fit`` אחת, עם שם הכלי, **שמות** הארגומנטים והמספרים.
בלי זה לא היה אפשר לדעת אם 256,000 צר מדי לתהליך נפוץ — רק מתלונות של סוכנים. גוף של
כלי קריאה רץ בחוט עובד (``asyncio.to_thread``, שמעתיק את ה-``Context``), והפנקס עצמו —
רשימה — הוא אותו אובייקט בעותק שבחוט, ולכן מה שנכתב שם מגיע ל-``call_tool``.
``tests/test_mcp_logging_visible.py`` בודק את זה בתהליך נקי ולא ב-``caplog``. מחוץ
ל-``recording`` (קריאה ישירה, הרשת שמסרבת אחרי שהגוף חזר) לא נרשם דבר.
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Callable, Iterator, Literal, Mapping, overload

from .answer_size import (
    ANSWER_TOO_LARGE,
    BYTE_BUDGET_REASON,
    OUTPUT_BYTE_BUDGET,
    list_item_cost,
    nonempty_list_bytes,
    wire_json,
    with_values,
)

#: מה שנרשם על תשובה אחת: הקוד (``answer_too_large`` או ``byte_budget``) והמספרים שלו.
Fit = tuple[str, dict[str, int]]

_FITS: contextvars.ContextVar[list[Fit] | None] = contextvars.ContextVar("answer_fits", default=None)


@contextlib.contextmanager
def recording() -> Iterator[list[Fit]]:
    """פנקס לקריאה אחת: כל :func:`too_large` ו-:func:`cut` שבתוכו נכתבים אליו."""
    fits: list[Fit] = []
    token = _FITS.set(fits)
    try:
        yield fits
    finally:
        _FITS.reset(token)


def _record(code: str, numbers: dict[str, int]) -> None:
    fits = _FITS.get()
    if fits is not None:
        fits.append((code, numbers))


def too_large(size: int | None, *, budget: int = OUTPUT_BYTE_BUDGET) -> dict[str, Any]:
    """הליבה של סירוב ``answer_too_large``: ``error``, ``bytes`` (כשנמדד) ו-``max``.

    ``bytes`` הוא גודל התשובה שהייתה נשלחת, נמדד ולא מוערך, ולכן ``bytes > max`` תמיד;
    ``None`` רק ברשת, על תוצאה שאי אפשר למדוד. הקורא מקיף את זה ב-``"ok": False``
    ובהקשר שלו, בסדר שלו.
    """
    core: dict[str, Any] = {"error": ANSWER_TOO_LARGE}
    if size is not None:
        core["bytes"] = size
    core["max"] = budget
    _record(ANSWER_TOO_LARGE, {key: core[key] for key in ("bytes", "max") if key in core})
    return core


def cut(**numbers: int) -> str:
    """הסיבה של חיתוך בתקציב הבתים, ``byte_budget`` — ורישום שלו עם ``numbers``.

    נקרא במקום שבו החיתוך נכנס לתשובה שחוזרת, ולא בתוך סורק שהתוצאה שלו עוד עשויה
    להיזרק; ``numbers`` הוא מה שיגיד משהו למי שקורא את הלוג — כמה חזר, מתוך כמה.
    """
    _record(BYTE_BUDGET_REASON, dict(numbers))
    return BYTE_BUDGET_REASON


class Attempt:
    """ניסיון אחד לבנות תשובה, עם מה שנרשם בו — שעובר לפנקס של הקריאה רק כשהוא נבחר.

    ``codekeeper_get_file`` מנסה את אותה תשובה עד שלוש פעמים — עם המטא-דאטה, ובלעדיה
    (``backend._fit_with_file_meta``) — ומחזיר אחת. חיתוך או סירוב שנרשמו בניסיון שנזרק
    לא קרו מבחינת מי שקורא את הלוג, ולכן הם אינם מגיעים אליו.
    """

    def __init__(self) -> None:
        self.fits: list[Fit] = []

    @property
    def cut(self) -> bool:
        """האם משהו בתשובה נחתך בתקציב הבתים (``byte_budget``)."""
        return any(code == BYTE_BUDGET_REASON for code, _ in self.fits)

    def keep(self, answer: dict[str, Any]) -> dict[str, Any]:
        """הניסיון הזה נבחר: מה שנרשם בו עובר לפנקס של הקריאה, והתשובה חוזרת כמו שהיא."""
        outer = _FITS.get()
        if outer is not None:
            outer.extend(self.fits)
        return answer


@contextlib.contextmanager
def attempt() -> Iterator[Attempt]:
    """פנקס נפרד לניסיון אחד; שום דבר ממנו אינו מגיע לקריאה עד :meth:`Attempt.keep`."""
    trial = Attempt()
    token = _FITS.set(trial.fits)
    try:
        yield trial
    finally:
        _FITS.reset(token)


def format_fits(fits: list[Fit]) -> str:
    """``answer_too_large bytes=… max=…; byte_budget returned=… of=…`` — מספרים וקודים בלבד."""
    return "; ".join(
        " ".join([code, *(f"{key}={value}" for key, value in numbers.items())]) for code, numbers in fits)


#: רשימה אחת ב-``cuts`` של :func:`fit_lists` — ``(הרשימה, מפתח הדגל)``. הרשימה
#: היא מפתח בראש התשובה (``"toc"``), או מסלול לרשימה אחת פנימה (``("file", "tags")``).
#: ב-:func:`fit_refusal` המסלול יכול להוביל גם למחרוזת (``("file", "description")``),
#: ואז המפתח השני הוא השדה שמקבל את הגודל שלה כשהיא יורדת (``description_bytes``).
Cut = tuple[str | tuple[str, ...], str]


def fit_line_range(
    answer: dict[str, Any],
    *,
    text_paths: tuple[tuple[str, ...], ...],
    range_path: tuple[str, ...],
    budget: int,
) -> tuple[dict[str, Any] | None, int]:
    """תשובת טווח שורות בתוך ``budget`` בתים **כפי שהיא נשלחת** — וגודלה.

    ``answer`` הוא תשובה שכבר נושאת טווח מ-``handlers.apply_line_range``: הטקסט החתוך
    בכל מסלול ב-``text_paths`` (בקובץ שמור גדול הוא יושב גם ב-``code`` וגם ב-
    ``content``, ולכן יש כמה), ובלוק ה-``range`` ב-``range_path``. שני הכלים —
    ``codekeeper_get_file`` ו-``codekeeper_get_repo_file`` — עוברים כאן, כמו
    שהם עוברים ב-``handlers.normalize_line_range`` וב-``handlers.apply_line_range``.

    **טווח שאינו נכנס נגמר מוקדם, על גבול שורה — ולא נדחה.** זה חיתוך בלי אובדן:
    ``range.end`` הוא השורה האחרונה שבאמת חזרה, ``range.truncated`` נדלק, ו-
    ``range.truncation_reason`` הוא ``byte_budget``. הקריאה הבאה מתחילה ב-
    ``end + 1``, ושום שורה אינה חוזרת פעמיים או הולכת לאיבוד. ``truncated`` בלי
    סיבה נשאר מה שהיה: ``end`` שביקשו מעבר לסוף הקובץ, וקוצץ אליו.

    **המדידה מצטברת, ולא מסדרלת את הטקסט כולו** (קריאת טווח במראה יכולה להגיע
    ל-10MB): נמדדת התשובה עם טקסט ריק ועם בלוק ``range`` במקרה הגרוע שלו —
    ``end`` בגודל ``total_lines``, והדגל והסיבה כבר בתוכו — ואז עלות כל שורה
    לבדה, עד שהתקציב נגמר. העלות מדויקת ולא הערכה: ה-escaping של מחרוזת JSON הוא
    לפי תו, ולכן מחרוזת של שורות מחוברות ב-``\\n`` עולה בדיוק את סכום השורות ועוד
    שני בתים (``\\n`` כתוב כשני תווים) בין כל שתיים. רק כשכל השורות נכנסות
    התשובה המקורית נמדדת כולה — ואז היא ממילא חסומה בתקציב.

    **ותשובה שנכנסת כמו שהיא אינה נחתכת.** השמורה של המקרה הגרוע גדולה מה-``range``
    של תשובה שאינה נחתכת בדגל ובסיבה, ולכן כשהספירה הגרועה נעצרת לפני הסוף נבדק
    פעם אחת גם ה-``range`` האמיתי: אם בו כל השורות נכנסות, התשובה חוזרת בית-בית.
    עד שזה נוסף (ריוויו על PR #3492, דרך טסט על מקרים אקראיים) תשובה שנכנסה בתקציב
    עד כדי כמה עשרות בתים נחתכה בשורה האחרונה שלה.

    ``(None, size)`` — כשגם השורה הראשונה לבדה אינה נכנסת. ``size`` הוא מה
    שהושווה לתקציב: התשובה הקטנה ביותר שנושאת תוכן, כלומר השורה הראשונה בלבד.
    לכן ``size > budget`` תמיד כאן, והקורא בונה ממנו את הסירוב.
    """
    rng = _value_at(answer, range_path)
    text = _value_at(answer, text_paths[0])
    lines = text.split("\n")
    start = rng["start"]
    worst = {**rng, "end": rng["total_lines"], "truncated": True,
             "truncation_reason": BYTE_BUDGET_REASON}
    base = with_values(answer, {range_path: worst, **{path: "" for path in text_paths}})
    copies = len(text_paths)

    def cost(i: int) -> int:
        return copies * (len(wire_json(lines[i])) - 2 + (2 if i else 0))

    worst_base = len(wire_json(base))
    size = worst_base
    kept = 0
    while kept < len(lines) and size + cost(kept) <= budget:
        size += cost(kept)
        kept += 1
    if kept < len(lines):
        # **השמורה של המקרה הגרוע אינה סיבה לחתוך תשובה שנכנסת.** ``range`` במקרה
        # הגרוע נושא ``truncated: true`` וסיבה, ותשובה שאינה נחתכת אינה נושאת אותם —
        # ולכן תשובה שנכנסת בתקציב עד כדי כמה עשרות בתים הייתה נחתכת בשורה האחרונה
        # שלה. כאן נבדק פעם אחת אם התשובה **כמו שהיא** נכנסת: ה-``range`` האמיתי, ושאר
        # השורות באותה עלות. הבדיקה נעצרת ברגע שהתקציב עבר, ולכן היא חסומה בו.
        real = len(wire_json(with_values(answer, {path: "" for path in text_paths})))
        real += size - worst_base
        for i in range(kept, len(lines)):
            real += cost(i)
            if real > budget:
                break
        else:
            kept = len(lines)
    if kept == len(lines):
        return answer, len(wire_json(answer))
    if not kept:
        return None, worst_base + cost(0)
    fitted = with_values(answer, {
        range_path: {**rng, "end": start + kept - 1, "truncated": True,
                     "truncation_reason": cut(returned=kept, of=len(lines))},
        **{path: "\n".join(lines[:kept]) for path in text_paths},
    })
    return fitted, len(wire_json(fitted))


def _value_at(answer: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = answer
    for key in path:
        node = node[key]
    return node


def fit_read(
    answer: dict[str, Any],
    *,
    ranged: bool,
    text_paths: tuple[tuple[str, ...], ...],
    range_path: tuple[str, ...],
    refuse: Callable[[int, int | None], dict[str, Any]],
    budget: int = OUTPUT_BYTE_BUDGET,
) -> dict[str, Any]:
    """קריאת קובץ — מלאה או טווח — בתוך ``budget``, או הסירוב שהקורא בונה. **השגרה האחת.**

    שני הכלים שקוראים קובץ, ``codekeeper_get_file`` ו-``codekeeper_get_repo_file`` (וגם פריט
    קובץ ב-``codekeeper_read_batch``), עוברים כאן, ומה ששונה ביניהם נמסר כפרמטר: איפה
    הטקסט ואיפה בלוק ה-``range`` (``text_paths``/``range_path``), ואיך נראה הסירוב —
    ``refuse(size, start)``, כש-``start`` הוא השורה שגם לבדה אינה נכנסת, או ``None``
    לקריאה מלאה. עד הריוויו על #3492 אלה היו שתי שגרות עם אותו עץ החלטה, והן כבר התפצלו.

    * **טווח** — :func:`fit_line_range`: נכנס כמו שהוא, נגמר מוקדם על גבול שורה, או סירוב.
    * **קריאה מלאה** — נכנסת כמו שהיא, או סירוב עם ``bytes`` שנמדד.

    **``ranged`` הוא מה שהקורא ביקש, ולא צורת התשובה** (WARN-002 בריוויו Han על #3492).
    עד כאן ``codekeeper_get_file`` הסתעף לפי ``range`` במסמך, ו-``_clean`` מעביר הלאה כל
    שדה שנשמר: מסמך עם שדה ``range`` משלו שלח קריאה מלאה לכאן, וקרס ב-``KeyError``. זה
    אותו כלל שכתוב ב-``server.py`` ליד ``get_file`` על ``query``/``toc``/``section``.
    בקובץ ממראה זה **לא היה באג** — ה-``range`` שם נבנה בקוד שלנו, ב-``RepoBackend.get_file``,
    ואין בו שדה של משתמש — אבל כשיש שגרה אחת, יש לה גם כלל אחד.
    """
    if ranged:
        fitted, size = fit_line_range(answer, text_paths=text_paths, range_path=range_path, budget=budget)
        if fitted is not None:
            return fitted
        return refuse(size, _value_at(answer, range_path)["start"])
    size = len(wire_json(answer))
    if size <= budget:
        return answer
    return refuse(size, None)


def fit_refusal(
    refusal: dict[str, Any], cuts: tuple[Cut, ...], notes: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """סירוב שנושא את ההקשר, בתוך ``OUTPUT_BYTE_BUDGET`` — ב-:func:`fit_lists`, לא בעותק.

    ``cuts`` הם השדות שבתוך ההקשר שמותר לוותר עליהם, כמו שהקורא מסר אותם ל-
    ``docs_handlers.answer_section`` (``refusal_cuts``); בקובץ שמור — ``file.tags`` ו-
    ``file.description``, בכלי התיעוד — אף אחד, ואז הסירוב חוזר כמו שהוא.

    **רשימה נחתכת קודם, ובלי חיתוך משלו כאן:** זה אותו :func:`fit_lists` שחותך את
    המפה ואת ההצעות, עם הדגל ``*_truncated`` לצד הרשימה שנחתכה, ו-``floor`` אומר לו
    מה לעשות כשגם ריקה הרשימה אינה מספיקה — להחזיר את הסירוב כשהיא ריקה ומסומנת.

    **ומחרוזת יורדת שלמה, עם הגודל שלה במקומה** (#3489, בצד הקריאה). מחרוזת אינה
    נחתכת — חיתוך בלי סימן הוא ``silent-truncation-at-sink``, ותיאור שנחתך באמצע
    נקרא כתיאור שלם. לכן כשגם אחרי הרשימות הסירוב גדול מהתקציב, המחרוזות שב-``cuts``
    יורדות אחת אחרי השנייה, בסדר שלהן, וכל אחת מוחלפת בשדה שכתוב לצידה ב-``cuts``
    — ``file.description_bytes``, מספר בתי ה-UTF-8 של מה שירד. שדה ה-``*_bytes``
    מופיע **רק** כשהמחרוזת ירדה, ולכן נוכחותו היא הסימן. עד כאן סירוב כזה נשא את
    התיאור כולו, ותיאור של 200,000 תווים עבריים הביא את הסירוב ל-400,523 בתים —
    בדיוק ברגע שבו הקורא הכי צריך תשובה קריאה. השורש — כותבים שאינם אוכפים תקרה על
    התיאור ועל התגיות — ב-#3489, והמנגנון הזה נשאר גם אחריו: מסמכים ישנים כבר שמורים.

    ``notes`` — משפט לכל מחרוזת שיורדת, לפי השדה שמקבל את הגודל שלה (``description_bytes``),
    שנוסף ל-``hint``: מי שמקבל סירוב בלי התיאור צריך לדעת איך מתקנים את התיאור.

    התקציב הוא ``OUTPUT_BYTE_BUDGET`` בלי שמורה: סירוב חוזר מ-``codekeeper_get_file``
    כמו שהוא, בלי ``found``/``status`` סביבו.
    """
    if not cuts:
        return refusal
    fitted, size = fit_lists(refusal, cuts=cuts, budget=OUTPUT_BYTE_BUDGET, floor=True)
    for key, size_key in cuts:
        if size <= OUTPUT_BYTE_BUDGET:
            break
        path = _as_path(key)
        parent = _dict_at(fitted, path[:-1])
        value = parent.get(path[-1]) if parent is not None else None
        if not isinstance(value, str):
            continue
        smaller = {name: item for name, item in parent.items() if name != path[-1]}
        smaller[size_key] = len(value.encode("utf-8"))
        fitted = with_values(fitted, {path[:-1]: smaller}) if path[:-1] else smaller
        note = (notes or {}).get(size_key)
        if note:
            # הרמז נוסף **לפני** המדידה, כך שגם הוא בתוך התקציב — ובלעדיו סירוב שמפנה
            # לצורה אחרת של אותו כלי, שנתקלת באותה מחרוזת, הוא מעגל (ריוויו Han על #3492).
            fitted = {**fitted, "hint": with_note(fitted.get("hint"), note)}
        size = len(wire_json(fitted))
    return fitted


def with_note(hint: str | None, note: str) -> str:
    """``hint`` ועוד ``note`` אחריו — או ``note`` לבדו כשאין עדיין ``hint``."""
    return f"{hint} {note}" if hint else note


def _dict_at(answer: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any] | None:
    """האובייקט שבמסלול (``()`` — התשובה עצמה), או ``None`` כשאין שם אובייקט."""
    node: Any = answer
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, dict) else None


def _as_path(key: str | tuple[str, ...]) -> tuple[str, ...]:
    """מפתח של רשימה ב-``cuts`` כמסלול: ``"toc"`` הוא ``("toc",)``."""
    return key if isinstance(key, tuple) else (key,)


def _list_at(answer: dict[str, Any], path: tuple[str, ...]) -> list | None:
    """הרשימה שבמסלול, או ``None`` כשאין שם רשימה.

    **ובלי רשימה — אין מה לחתוך, ואין מה לגעת בו.** מסלול כזה יוצא מהחיתוך כולו,
    והערך שבו — חסר, ``None``, מחרוזת — נשאר בתשובה כמו שהוא. זה חשוב ב-``file.tags``,
    שמגיע מהמסד ולא מהקוד שלנו: מסמך בלי ``tags``, או עם ``tags: null``, אינו מקבל
    ``tags: []`` ודגל בגלל שהסירוב שלו גדול.
    """
    node: Any = answer
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, list) else None


@overload
def fit_lists(
    answer: dict[str, Any], *, cuts: tuple[Cut, ...], budget: int, floor: Literal[True],
    record: bool = ...,
) -> tuple[dict[str, Any], int]: ...


@overload
def fit_lists(
    answer: dict[str, Any], *, cuts: tuple[Cut, ...], budget: int, floor: Literal[False] = ...,
    record: bool = ...,
) -> tuple[dict[str, Any] | None, int]: ...


def fit_lists(
    answer: dict[str, Any], *, cuts: tuple[Cut, ...], budget: int, floor: bool = False,
    record: bool = False,
) -> tuple[dict[str, Any] | None, int]:
    """התשובה בתוך ``budget`` בתים כפי שהיא נשלחת, בחיתוך רשימות מהסוף — וגודלה.

    ``cuts`` הוא ``(הרשימה, מפתח הדגל)``, **בסדר שבו מוותרים עליהן**: הרשימה
    הראשונה נחתכת מהסוף ראשונה, בזמן שכל המאוחרות לה מלאות, ורק אם היא רוקנה
    לגמרי והתשובה עדיין גדולה עוברים לחתוך את הבאה. בכל רשימה נשמרת הקידומת
    הארוכה ביותר שנכנסת — מה שנחתך הוא תמיד הסוף, כך שהמועמדים נשארים בסדר המסמך.

    **הרשימה היא מפתח בראש התשובה, או מסלול לרשימה אחת פנימה.** ``"toc"`` הוא
    רשימה בראש התשובה (עומק 0, כל הקוראים עד #3472); ``("file", "tags")`` היא
    רשימה בתוך האובייקט ``file`` (עומק 1, :func:`fit_refusal`). הדגל יושב **לצד
    הרשימה**, באותו אובייקט — ``toc_truncated`` בראש התשובה, ``file.tags_truncated``
    בתוך ``file``. העלות של כל פריט נמדדת בעומק שבו הוא יושב
    (:func:`~mcp_server.answer_size.list_item_cost` עם ``depth``), ובעומק 0 היא
    בדיוק המספרים שהיו כאן לפני שהעומק נוסף — ``tests/test_mcp_file_sections.py``
    מריץ את אותם קלטים דרך הצורה הקודמת ומשווה החלטה-החלטה. מסלול שאין בו רשימה
    אינו נחתך ואינו נוגע בתשובה (:func:`_list_at`).

    **הדגל נדלק רק כשבאמת נחתך פריט מהרשימה שלו.** תשובה שנכנסת חוזרת כמו שהיא —
    אותו אובייקט — ולכן כל תשובה שנכנסה עד היום לא משתנה בבית אחד (אפס-דיף).
    רשימה ריקה לא נחתכת ולא מדליקה דגל.

    ``(None, size)`` — כשגם אחרי שכל הרשימות רוקנו התשובה גדולה מהתקציב; ``size`` הוא
    גודל התשובה עם רשימות ריקות. מה שנשאר אז הוא מה שאינו רשימה, ואת זה כאן אין מה
    לחתוך (ראו :data:`ANSWER_TOO_LARGE`). **ועם ``floor``** — במקום ``None``, התשובה
    כשכל הרשימות ריקות ומסומנות: הקטנה ביותר שהפונקציה הזו יכולה לתת, בשביל סירוב
    שאין לו לאן לסרב הלאה (:func:`fit_refusal`).

    **המדידה מצטברת, ולעולם לא מסדרלת את התשובה המלאה.** הצורה הקודמת קראה
    ``wire_json(answer)`` על התשובה עם כל הפריטים כדי למדוד אותה — וזו בדיוק
    המחרוזת הענקית שקובץ עוין יכול לנפח למאות מגה-בייט לפני החיתוך (ריוויו על
    PR #3470; מפת כותרות שכל פריט בה נושא את כל ה-breadcrumb). במקום זה נמדדת
    התשובה עם רשימות **ריקות** (קטנה), ועלות כל פריט נמדדת לבדה
    (:func:`~mcp_server.answer_size.list_item_cost`, אותה מדידה של
    ``codekeeper_read_batch``). הסכום הוא **חסם עליון** (העלות מחמירה בפסיק),
    ולכן ``total <= budget`` מבטיח שהתשובה האמיתית נכנסת — ואז, ורק אז, מסדרלים
    אותה פעם אחת (מחרוזת חסומה בתקציב). המחרוזת הגדולה ביותר שנבנית אי-פעם היא
    התקציב ועוד פריט בודד, לא התשובה כולה.

    **אפס-דיף.** כל תשובה שנכנסת חוזרת כאובייקט המקורי, ומספר הבתים שמוחזר הוא
    ``wire_json(answer)`` המדויק — כך שכל תשובה שנכנסה עד היום זהה לבית. הקורפוס
    כולו נכנס בפער גדול (המפה הגדולה שנמדדה ~132KB מול תקציב 256KB), ולכן חל עליו
    המסלול הזה בלבד. החיתוך פועל רק על קלט שאינו בקורפוס, ושם הוא שמרני בפריט
    אחד לכל היותר (חסם ה"תקציב ועוד פריט").
    """
    paths = [_as_path(key) for key, _ in cuts]
    flag_of = {path: path[:-1] + (flag,) for path, (_, flag) in zip(paths, cuts, strict=True)}
    found = {path: _list_at(answer, path) for path in paths}
    lists = {path: items for path, items in found.items() if items is not None}
    live = [path for path in paths if path in lists]
    base = with_values(answer, {path: [] for path in live})
    base_size = len(wire_json(base))
    item_costs = {path: [list_item_cost(item, depth=len(path) - 1) for item in lists[path]]
                  for path in live}
    total = base_size + sum(
        nonempty_list_bytes(len(path) - 1) + sum(item_costs[path]) for path in live if lists[path]
    )
    # ``total`` מחמיר בפסיק אחד לכל רשימה לא-ריקה, ולכן ``total - real`` חסום ב-
    # ``len(live)``. מסדרלים את התשובה המלאה **רק** כשהיא בטווח הזה מהתקציב —
    # כלומר קרובה אליו וקטנה. במקרה הענק ``total`` גדול מהתקציב בהרבה יותר מזה,
    # ולכן לא בונים את המחרוזת הענקית: מדלגים ישר לחיתוך.
    if total <= budget + len(live):
        real = len(wire_json(answer))
        if real <= budget:
            return answer, real

    # לא נכנסת: חותכים מהסוף, רשימה-רשימה לפי סדר הוויתור, לפי חסם העלות בלבד —
    # בלי לסדרל את התשובה המלאה. הדגלים אינם ב-``running``, ולכן זו הערכה; האימות
    # המדויק בא מיד אחריה, על התשובה החתוכה שכבר חסומה בגודלה.
    kept = {path: list(lists[path]) for path in live}
    flags: dict[tuple[str, ...], bool] = {}
    running = total
    for path in live:
        if running <= budget:
            break
        items, costs = kept[path], item_costs[path]
        while items and running > budget:
            running -= costs[len(items) - 1]
            items.pop()
            flags[flag_of[path]] = True
            if not items:
                running -= nonempty_list_bytes(len(path) - 1)

    # אימות מדויק: הדגלים הוסיפו בתים שלא נספרו ב-``running``, ולכן ייתכן שצריך
    # להוריד עוד פריט. כל מדידה כאן היא על תשובה שכבר חסומה בתקציב (ועוד פריט),
    # לעולם לא על התשובה המלאה. מורידים מהרשימה הראשונה שעדיין נושאת פריט (אותו
    # סדר ויתור), ועד שגם ריקות אינן נכנסות — ``answer_too_large``, או עם ``floor``
    # התשובה הריקה עצמה.
    fitted = with_values(answer, {**kept, **flags})
    size = len(wire_json(fitted))
    while size > budget:
        trimmable = next((path for path in live if kept[path]), None)
        if trimmable is None:
            return (fitted if floor else None), size
        kept[trimmable].pop()
        flags[flag_of[trimmable]] = True
        fitted = with_values(answer, {**kept, **flags})
        size = len(wire_json(fitted))
    if record:
        # ``record`` — רק כשהתשובה שנחתכה היא זו שחוזרת (``docs_handlers._fit_or_refuse``).
        # ``fit_refusal`` אינו מבקש: שם החיתוך הוא חלק מסירוב, שכבר נרשם כ-``answer_too_large``.
        for path in live:
            if flag_of[path] in flags:
                cut(returned=len(kept[path]), of=len(lists[path]))
    return fitted, size
