"""כללי CSS מטקסט — לשומרים שקוראים CSS כטקסט ולא מריצים דפדפן.

**למה קובץ משותף.** כמה שומרים קוראים כללי CSS כטקסט: ``tests/test_sticky_notes_touch_action.py``
מקובץ CSS, ו-``tests/test_navbar_and_search_bars_css.py`` מבלוקי ``<style>`` של תבניות. עותק שני
של הפרסור היה נסחף מהראשון ביום שאחד מהם מתוקן — למשל ביום שמישהו מלמד אותו בורר שיש בו
פסיק בתוך סוגריים, כמו ``:has(a, b)``.

**ומה הוא לא עושה.** זה אינו פרסור CSS מלא. ``@media`` ודומיו נבלעים: הכלל הפנימי נמצא כמו כל
כלל, בלי התנאי שלו. מי שההחלטה שלו תלויה בתנאי צריך לבדוק אותו בעצמו.
"""
from __future__ import annotations

import re
from pathlib import Path

_STYLE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL)
# Jinja יכול להופיע בתוך בלוק סגנון, והסוגריים המסולסלים שלו היו נקראים ככלל CSS.
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
# הערות מוסרות לפני הפרסור: הסבר ליד כלל מזכיר לעיתים בכוונה את הצורה הפסולה, ובלי ההסרה
# שומר היה נכשל על התיעוד של עצמו.
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# הכלל הפנימי ביותר: ``{`` ו-``}`` אינם בתוך הבורר ובתוך הגוף.
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)


def split_selector_list(selector: str) -> list[str]:
    """פיצול רשימת בוררים בפסיקים שמחוץ לסוגריים — ``:has(a, b)`` הוא בורר אחד."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in selector:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return parts


def css_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """``(בורר בודד, {מאפיין: ערך})`` לכל כלל ב-``css``. רשימת בוררים מפוצלת לבוררים בודדים."""
    out = []
    for selector_list, body in _RULE.findall(_COMMENT.sub("", css)):
        declarations = {}
        for declaration in body.split(";"):
            prop, sep, value = declaration.partition(":")
            if sep:
                declarations[prop.strip()] = " ".join(value.split())
        for selector in split_selector_list(" ".join(selector_list.split())):
            out.append((selector, declarations))
    return out


def template_css(path: Path) -> str:
    """כל בלוקי ה-``<style>`` של תבנית, מחוברים, בלי Jinja."""
    return _JINJA.sub("", "\n".join(_STYLE.findall(path.read_text(encoding="utf-8"))))


_WHERE = re.compile(r":where\((?:[^()]|\([^()]*\))*\)")
_ATTRIBUTE = re.compile(r"\[[^\]]*\]")
# ``:before`` ו-``:after`` בנקודתיים אחת הם פסאודו-אלמנטים לכל דבר, ולא פסאודו-מחלקות.
_PSEUDO_ELEMENT = re.compile(r"::[\w-]+|:(?:before|after|first-line|first-letter)(?![\w-])")


def specificity(selector: str) -> tuple[int, int, int]:
    """המשקל של בורר בודד: ``(מזהים, מחלקות+מאפיינים+פסאודו-מחלקות, טיפוסים+פסאודו-אלמנטים)``.

    לפי Selectors 4, הסעיף "Calculating a selector's specificity". ``:where()`` שוקל אפס, ולכן
    הוא מוסר לפני הספירה. **כל פסאודו-מחלקה אחרת עם סוגריים נדחית** (``ValueError``):
    ``:is()``/``:not()``/``:has()`` שוקלים את הארגומנט הכבד ביותר שלהם, ו-``:nth-child(… of S)``
    שוקל גם את ``S`` — וזה לא ממומש כאן. משקל שגוי היה עובר בשקט; בורר שנדחה מכריח החלטה.
    """
    s = _WHERE.sub("", selector)
    attributes = len(_ATTRIBUTE.findall(s))
    # ערך של מאפיין יכול להכיל ``:``, ``.``, ``#`` ורווח — ``[data-theme^="shared:"]``.
    s = _ATTRIBUTE.sub("", s)
    if "(" in s:
        raise ValueError(f"בורר שהפונקציה אינה יודעת לשקלל: {selector}")
    pseudo_elements = len(_PSEUDO_ELEMENT.findall(s))
    s = _PSEUDO_ELEMENT.sub("", s)
    ids = len(re.findall(r"#[\w-]+", s))
    classes = len(re.findall(r"\.[\w-]+", s))
    pseudo_classes = len(re.findall(r":[\w-]+", s))
    types = len(re.findall(r"(?:^|[\s>+~])[a-zA-Z][\w-]*", s))
    return (ids, classes + attributes + pseudo_classes, types + pseudo_elements)
