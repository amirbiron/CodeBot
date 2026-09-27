#!/usr/bin/env python3
"""תצלום של כל מה שהפארסרים של התיעוד מחזירים — להשוואה לפני ואחרי שדרוג של ``markdown-it-py``.

**הראיה ששדרוג לא שינה התנהגות היא אפס-דיף**: אותו פלט בדיוק בסביבה הישנה ובחדשה. הסקריפט
רץ פעמיים, פעם בכל סביבה, מאותו עץ עבודה ועל אותו קורפוס, וכותב תצלום JSON בכל פעם. אחר כך
``compare`` משווה את שני התצלומים. זה אותו נימוק כמו ב-``scripts/docs_section_zero_diff.py``:
הערך הוא הדיף בין שתי ריצות, ו-CI רץ בסביבה אחת — ולכן זה כלי ידני ולא טסט.

**מה נכנס לתצלום:**

- ``maps`` — כל קובץ ``.md`` ו-``.rst`` תחת כל שורש: כל השדות של כל ``Section``, ה-TOC,
  ה-``includes``, מספר השורות וגיבוב שלהן — או הסירוב, עם סוג החריגה והארגומנטים שלה.
  לקובצי ``.md`` גם ``front_matter_end``.
- ``refusals`` — קלטים סינתטיים דרך ``docs_handlers.document_from_read``, כלומר בדיוק התשובה
  שהכלי מחזיר: ``\\r`` בודד, מעל ``MAX_SECTIONS``, קובץ ריק, BOM, front matter, ו-``binary`` או
  ``too_large``.
- ``hostile`` — צורות עוינות קטנות: טבלה רחבה, תבליטים, הגדרות קישור רצופות. מפות בלבד.
- ``oracle`` — כל המשפחות של ``tests/test_md_parser_oracle.py``, בשמן: אלה שב-
  ``_COMPARED_FAMILIES``, והמשפחה של כל שורה ב-``_KNOWN_DIVERGENCES`` לפי ה-``key`` שלה. לכל
  צורה: מה אנחנו מחזירים, מה cmark-gfm מחזיר, והאם מסכימים. ``oracle_titles`` — טקסט הכותרות
  במטריצת ההקשר.
- ``versions`` ו-``info_token_count`` — מידע בלבד, ואינם חלק מפסק הדין. ``token_count`` זז
  כששדרוג משנה את מספר הטוקנים בלי לשנות אף מפה, וזה בדיוק מה שמדידת העלות צריכה לדעת.

**פסק הדין:** ``maps``, ``refusals``, ``hostile`` ו-``oracle_titles`` זהים, וכל משפחה ב-``oracle``
זהה — **חוץ ממשפחות שהוכרזו מראש** ב-``--expected-change``. אותן ההשוואה מדווחת (כמה צורות
השתנו), ומשפחה שהוכרזה **ולא** השתנתה מפילה את ההשוואה גם היא: הכרזה שלא התקיימה היא הנחה
שגויה, ואם תישאר בפקודה היא תסתיר את השינוי הבא באותה משפחה.

**למה להכריז ולא רק לדווח.** שדרוג שמשנה מחלקה ידועה אינו אפס-דיף — ב-4.2.0 אלה
``source``/``search`` והטבלה שעוברת את תקרת התאים. בלי הכרזה הסקריפט היה אדום בדיוק על
השדרוג שהוא נבנה בשבילו, ומי שמתרגל לראות אותו אדום לא יראה את השינוי הבא. ההכרזה אומרת מה
צפוי להשתנות, והסקריפט מוכיח ששום דבר אחר לא השתנה.

**הקורפוס נמסר כארגומנט** (``--root NAME=PATH``), כדי ששתי הריצות יפרסרו את אותם בתים.
נסרקים כל הקבצים תחת השורש חוץ מ-``.git``, כמו ב-``scripts/compare_md_parser_to_cmark.py``.

``--family`` מצמצם את חלק האורקל למשפחות שנקבו בשמן (ברירת מחדל: כולן), לריצה מהירה בזמן
עבודה. ``compare`` נופל כששני התצלומים אינם מכילים אותן משפחות.

**האורקל נטען בטוען של** ``scripts/compare_md_parser_to_cmark.py`` **ולא בטוען שני**, כי שני
עותקים של "איך טוענים את קובץ הטסטים" היו נסחפים זה מזה. לכן הסקריפט דורש בשתי הסביבות את מה
שהאורקל דורש: ``cmarkgfm`` ו-``pytest``, מ-``requirements/development.txt``.

הסקריפט אינו כותב לשום קובץ מלבד ``--out``.

שימוש — שני מפרשים, אותו עץ עבודה, אותם שורשים::

    <python של הסביבה הישנה> scripts/md_parser_upgrade_zero_diff.py snapshot \\
        --root repo=. --root abp=/path/to/amir-bug-patterns --out /tmp/before.json
    <python של הסביבה החדשה> scripts/md_parser_upgrade_zero_diff.py snapshot \\
        --root repo=. --root abp=/path/to/amir-bug-patterns --out /tmp/after.json
    python scripts/md_parser_upgrade_zero_diff.py compare /tmp/before.json /tmp/after.json \\
        --expected-change commonmark_0_31_block_tag_list \\
        --expected-change table_over_autocomplete_cap

קוד יציאה של ``compare``: 0 — אפס דיף, מלבד מה שהוכרז, וכל מה שהוכרז אכן השתנה; 1 — הבדל;
2 — קלט שגוי (ארגומנט, או תצלום שאינו במבנה של הסקריפט הזה).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.metadata
import json
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
# לפני כל ייבוא מ-``services`` ומ-``mcp_server``: הסקריפט רץ כנקודת כניסה עצמאית,
# ו-``scripts`` אינה חבילה.
sys.path.insert(0, str(_REPO))

from mcp_server import docs_handlers  # noqa: E402
from services import doc_sections, md_parser, rst_parser  # noqa: E402

#: גרסת המבנה של התצלום. ``compare`` מסרב לתצלום בגרסה אחרת: השוואה בין שני מבנים
#: הייתה מדווחת הבדל על כל מפתח, או גרוע מזה — אפס הבדלים על מפתח שחסר באחד מהם.
_FORMAT = 1

#: קבוצות שחייבות להיות זהות בשני התצלומים, בלי הכרזה שפוטרת.
_EXACT_GROUPS = ("maps", "refusals", "hostile", "oracle_titles")

#: החבילות שהגרסאות שלהן נרשמות בתצלום.
_PACKAGES = ("markdown-it-py", "mdit-py-plugins", "cmarkgfm")

#: הסירובים המתועדים של הפארסרים ("ערוץ הכשל הוא חריגה בלבד" ב-``md_parser``). סירוב
#: כזה הוא **תוצאה**: הוא נרשם בתצלום ומושווה כמו כל תוצאה אחרת. כל חריגה אחרת היא
#: באג, והיא עולה ומפילה את הריצה.
_REFUSALS = (doc_sections.InconsistentLineEndings, doc_sections.TooManySections, TypeError)

#: כמה דוגמאות להדפיס לכל קבוצה או משפחה שיש בה הבדל.
_SHOWN = 5


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _document(doc: doc_sections.Document) -> dict[str, Any]:
    """כל מה שהמסמך המפורסר נושא. ``asdict`` ולא רשימת שדות ביד — שדה שיתווסף ל-``Section``
    ייכנס לתצלום מעצמו. השורות עצמן נכנסות כגיבוב, כי הן העותק של הקובץ."""
    return {
        "sections": [dataclasses.asdict(section) for section in doc.sections],
        "toc": doc_sections.build_toc(doc),
        "includes": list(doc.includes),
        "line_count": len(doc.lines),
        "lines_sha": _sha("\n".join(doc.lines)),
    }


def _refused(exc: BaseException) -> dict[str, Any]:
    """סירוב כתוצאה: סוג החריגה, והארגומנטים שלה (שורה, תקרה) כפי שהם."""
    return {
        "raised": type(exc).__name__,
        "args": [arg if isinstance(arg, (int, str)) else repr(arg) for arg in exc.args],
    }


def _parse(parser, text) -> dict[str, Any]:
    try:
        doc = parser.parse_document(text)
    except _REFUSALS as exc:  # סירוב מתועד — נרשם ומושווה, לא נבלע
        return _refused(exc)
    return _document(doc)


def _value_or_refused(function: Callable[[str], Any], text: str) -> Any:
    """ל-``front_matter_end`` ול-``token_count``, שעוברים באותו שער כניסה כמו ``parse_document``."""
    try:
        return function(text)
    except _REFUSALS as exc:  # אותו סירוב כמו של הפרסור — נרשם, לא נבלע
        return _refused(exc)


def _corpus_files(root: Path) -> list[Path]:
    """כל קובץ ``.md`` ו-``.rst`` תחת ``root``, חוץ ממה שתחת ``.git``."""
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix in (".md", ".rst")
        and path.is_file()
        and ".git" not in path.relative_to(root).parts
    )


def _maps(corpus: dict[str, tuple[Path, list[Path]]]) -> tuple[dict[str, Any], dict[str, Any]]:
    maps: dict[str, Any] = {}
    token_counts: dict[str, Any] = {}
    for name, (root, files) in corpus.items():
        for path in files:
            key = f"{name}:{path.relative_to(root).as_posix()}"
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                # נרשם כזה, עם גיבוב הבתים — שינוי בקובץ עדיין ייראה בהשוואה
                maps[key] = {"undecodable": True, "bytes_sha": hashlib.sha256(raw).hexdigest()}
                continue
            if path.suffix == ".rst":
                maps[key] = _parse(rst_parser, text)
                continue
            entry = _parse(md_parser, text)
            entry["front_matter_end"] = _value_or_refused(md_parser.front_matter_end, text)
            maps[key] = entry
            token_counts[key] = _value_or_refused(md_parser.token_count, text)
    return maps, token_counts


def _refusals() -> dict[str, Any]:
    """תשובות הכלי על קלטים שמסורבים או גבוליים — דרך ``document_from_read``, כמו בייצור."""
    many_md = "# h\n\n" * (doc_sections.MAX_SECTIONS + 1)
    many_rst = "Doc\n===\n\n" + "h\n-\n\n" * (doc_sections.MAX_SECTIONS + 1)
    cases = {
        "md_lone_cr_middle": (".md", "# a\n\nfoo\rbar\n"),
        "md_lone_cr_first_line": (".md", "# a\rb\n"),
        "md_mixed_crlf_and_lone_cr": (".md", "# a\r\n\r\nfoo\rbar\r\n"),
        "md_too_many_sections": (".md", many_md),
        "md_empty": (".md", ""),
        "md_bom_crlf": (".md", "﻿# a\r\n\r\ntext\r\n## b\r\n"),
        "md_front_matter_only": (".md", "---\ntitle: x\n---\n"),
        "md_front_matter_then_heading": (".md", "---\ntitle: x\n---\n# a\n"),
        "rst_too_many_sections": (".rst", many_rst),
        "rst_lone_cr": (".rst", "Doc\n===\n\nfoo\rbar\n"),
        "rst_empty": (".rst", ""),
    }
    out: dict[str, Any] = {}
    for name, (suffix, text) in cases.items():
        target = docs_handlers.DocsTarget("fixture", f"x{suffix}", suffix)
        res = {
            "ok": True, "status": "ok", "content": text,
            "file": {"path": target.path, "ref": "HEAD", "resolved_commit": "fixed"},
        }
        answer = docs_handlers.document_from_read(res, target)
        if isinstance(answer, dict):
            out[name] = {"answer": answer}
        else:
            out[name] = {"loaded": _document(answer.doc), "context": answer.context}
    for status in ("binary", "too_large"):
        target = docs_handlers.DocsTarget("fixture", "x.md", ".md")
        res = {"ok": True, "status": status, "file": {"path": target.path}}
        out[f"status_{status}"] = {"answer": docs_handlers.document_from_read(res, target)}
    out["md_not_a_string"] = _parse(md_parser, None)
    return out


def _hostile() -> dict[str, Any]:
    shapes = {
        "table_100x100": "|" + "a|" * 100 + "\n|" + "-|" * 100 + "\n" + "|\n" * 100,
        "bullets_1000": "- item\n" * 1000,
        "empty_bullets_1000": "-\n" * 1000,
        "nested4_1000": "- - - - a\n" * 1000,
        "ordered_1000": "1. a\n" * 1000,
        "refs_500": "".join(f"[r{i}]: b\n" for i in range(500)),
        "refs_then_heading": "".join(f"[r{i}]: b\n" for i in range(50)) + "# after\n",
        "blank_1000": "\n" * 1000,
        "quote20_100": (">" * 20 + "\n") * 100,
        "thematic_1000": "***\n" * 1000,
    }
    return {name: _parse(md_parser, text) for name, text in shapes.items()}


def _load_oracle():
    """האורקל, דרך הטוען של ``scripts/compare_md_parser_to_cmark.py`` — אותו טוען, לא עותק.

    ``scripts`` אינה חבילה, ולכן הסקריפט האח מיובא בשם המודול שלו, והתיקייה נכנסת
    ל-``sys.path`` לזמן הייבוא בלבד — כמו ב-``tests/test_no_committed_pyc.py``. כשהסקריפט
    הזה רץ ישירות היא כבר שם; ההכנסה מכסה את מי שטוען אותו לפי נתיב, כמו הטסטים שלו.
    ‏``remove`` ולא ``pop(0)``: הייבוא עצמו מכניס את שורש הריפו לראש ``sys.path``.
    """
    scripts = str(_REPO / "scripts")
    sys.path.insert(0, scripts)
    try:
        from compare_md_parser_to_cmark import _load_oracle as load
    finally:
        sys.path.remove(scripts)
    return load()


def _oracle_families(oracle) -> dict[str, Callable[[], Iterable[str]]]:
    """כל משפחה בשמה: ``_COMPARED_FAMILIES``, ומשפחת כל שורה ב-``_KNOWN_DIVERGENCES``."""
    families: dict[str, Callable[[], Iterable[str]]] = dict(oracle._COMPARED_FAMILIES)
    for row in oracle._KNOWN_DIVERGENCES:
        if row.key in families:
            # שני שמות זהים היו משאירים בתצלום רק אחת מהמשפחות, בלי שאיש ידע
            raise RuntimeError(f"שם משפחה כפול באורקל: {row.key}")
        families[row.key] = lambda row=row: (text for text, _agrees in row.family())
    return families


def _ours_or_refused(oracle, text: str) -> Any:
    try:
        return [list(pair) for pair in oracle._ours(text)]
    except _REFUSALS as exc:  # סירוב על צורה מחוללת — נרשם ומושווה, לא נבלע
        return _refused(exc)


def _oracle(oracle, families, names: list[str]) -> tuple[dict[str, Any], list[Any]]:
    rows: dict[str, Any] = {}
    for name in names:
        shapes = []
        for text in families[name]():
            ours = _ours_or_refused(oracle, text)
            theirs = [list(pair) for pair in oracle._oracle_sections(text)]
            shapes.append(
                {"text_sha": _sha(text), "ours": ours, "theirs": theirs, "agree": ours == theirs}
            )
        rows[name] = shapes
    # טקסט הכותרת, על מטריצת ההקשר — מה ש-``_compare_titles`` בודק, בלי ה-assert
    titles: list[Any] = []
    if "context_matrix" in names:
        for text in families["context_matrix"]():
            try:
                sections = md_parser.parse_document(text).sections
                ours = [[s.level, s.heading_line, s.title] for s in sections]
            except _REFUSALS as exc:  # נרשם ומושווה, לא נבלע
                ours = _refused(exc)
            titles.append({"ours": ours, "theirs": [list(t) for t in oracle._oracle_titles(text)]})
    return rows, titles


def _snapshot(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    corpus: dict[str, tuple[Path, list[Path]]] = {}
    for item in args.root:
        name, separator, raw_path = item.partition("=")
        if not (separator and name and raw_path):
            parser.error(f"--root הוא NAME=PATH, התקבל: {item!r}")
        if name in corpus:
            parser.error(f"השם {name!r} מופיע פעמיים ב---root")
        root = Path(raw_path).expanduser().resolve()
        if not root.is_dir():
            parser.error(f"אינו תיקייה: {root}")
        files = _corpus_files(root)
        if not files:
            parser.error(f"אפס קובצי .md ו-.rst תחת {root} — תצלום של כלום אינו ראיה")
        corpus[name] = (root, files)
    # לפני העבודה הארוכה, לא אחריה: תיקייה חסרה הייתה נגלית רק בכתיבה, אחרי כל הפרסור
    if not args.out.parent.is_dir():
        parser.error(f"התיקייה של --out אינה קיימת: {args.out.parent}")

    oracle = _load_oracle()
    families = _oracle_families(oracle)
    names = list(dict.fromkeys(args.family)) if args.family else list(families)
    unknown = [name for name in names if name not in families]
    if unknown:
        parser.error(f"משפחות שאינן באורקל: {', '.join(unknown)}. הקיימות: {', '.join(families)}")

    maps, token_counts = _maps(corpus)
    oracle_rows, titles = _oracle(oracle, families, names)
    snapshot = {
        "format": _FORMAT,
        "versions": {package: importlib.metadata.version(package) for package in _PACKAGES},
        "maps": maps,
        "refusals": _refusals(),
        "hostile": _hostile(),
        "oracle": oracle_rows,
        "oracle_titles": titles,
        "info_token_count": token_counts,
    }
    args.out.write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8"
    )
    md_files = sum(1 for key in maps if key.endswith(".md"))
    shapes = sum(len(rows) for rows in oracle_rows.values())
    print(
        f"נכתב {args.out}: {md_files} קובצי md, {len(maps) - md_files} קובצי rst, "
        f"{len(snapshot['refusals'])} מקרי סירוב, {shapes} צורות ב-{len(oracle_rows)} משפחות; "
        + ", ".join(f"{package} {version}" for package, version in snapshot["versions"].items())
    )
    return 0


class _BadSnapshot(ValueError):
    """תצלום שאינו במבנה שהסקריפט הזה כותב."""


def _load_snapshot(path: Path) -> dict[str, Any]:
    """קורא תצלום **ובודק את המבנה שלו** לפני שמשהו ניגש לתוכו.

    הקובץ הגיע מחוץ לתהליך — אולי מגרסה אחרת של הסקריפט, אולי נערך ביד, אולי נקטע —
    ובלי הבדיקה, מפתח חסר או רשימה במקום מילון היו מפילים את ההשוואה ב-traceback באמצע
    הדוח במקום לומר איזה קובץ ואיזה שדה.
    """
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise _BadSnapshot(f"{path}: לא נקרא כתצלום JSON ({type(exc).__name__}: {exc})") from exc
    if not isinstance(data, dict):
        raise _BadSnapshot(f"{path}: התצלום אינו אובייקט JSON")
    if data.get("format") != _FORMAT:
        raise _BadSnapshot(f"{path}: גרסת מבנה {data.get('format')!r}, והסקריפט הזה כותב {_FORMAT}")
    for key in ("versions", "maps", "refusals", "hostile", "oracle", "info_token_count"):
        if not isinstance(data.get(key), dict):
            raise _BadSnapshot(f"{path}: השדה {key!r} חסר או אינו אובייקט")
    if not isinstance(data.get("oracle_titles"), list):
        raise _BadSnapshot(f"{path}: השדה 'oracle_titles' חסר או אינו רשימה")
    for family, shapes in data["oracle"].items():
        if not isinstance(shapes, list) or not all(
            isinstance(shape, dict) and isinstance(shape.get("text_sha"), str) for shape in shapes
        ):
            raise _BadSnapshot(f"{path}: המשפחה {family!r} אינה רשימה של צורות עם text_sha")
    return data


def _differences(old: Any, new: Any) -> tuple[list[str], list[str], list[str]]:
    """‏(רק בישן, רק בחדש, שונים) — מפתחות במילון, או אינדקסים ברשימה."""
    if isinstance(old, dict) and isinstance(new, dict):
        only_old = sorted(set(old) - set(new))
        only_new = sorted(set(new) - set(old))
        different = sorted(key for key in set(old) & set(new) if old[key] != new[key])
        return only_old, only_new, different
    if isinstance(old, list) and isinstance(new, list):
        common = min(len(old), len(new))
        only_old = [f"#{index}" for index in range(common, len(old))]
        only_new = [f"#{index}" for index in range(common, len(new))]
        different = [f"#{index}" for index in range(common) if old[index] != new[index]]
        return only_old, only_new, different
    return [], [], ["(הקבוצה אינה מאותו סוג בשני התצלומים)"]


def _compare(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        old, new = _load_snapshot(args.old), _load_snapshot(args.new)
    except _BadSnapshot as exc:
        parser.error(str(exc))
    expected = list(dict.fromkeys(args.expected_change or ()))
    absent = [name for name in expected if name not in old["oracle"] or name not in new["oracle"]]
    if absent:
        parser.error(f"--expected-change על משפחה שאינה בשני התצלומים: {', '.join(absent)}")

    lines = [f"ישן: {old['versions']}", f"חדש: {new['versions']}", ""]
    failed = False

    for group in _EXACT_GROUPS:
        only_old, only_new, different = _differences(old[group], new[group])
        lines.append(
            f"[{group}] רק בישן={len(only_old)} רק בחדש={len(only_new)} שונים={len(different)}"
        )
        for key in (only_old + only_new + different)[:_SHOWN]:
            lines.append(f"    {key}")
        failed |= bool(only_old or only_new or different)

    old_names, new_names = set(old["oracle"]), set(new["oracle"])
    if old_names != new_names:
        lines.append(
            "[oracle] לא אותן משפחות — "
            f"רק בישן: {sorted(old_names - new_names)}, רק בחדש: {sorted(new_names - old_names)}"
        )
        failed = True
    changed: set[str] = set()
    incomparable: set[str] = set()
    for name in sorted(old_names & new_names):
        before, after = old["oracle"][name], new["oracle"][name]
        if [shape["text_sha"] for shape in before] != [shape["text_sha"] for shape in after]:
            # המחוללים אינם אותו קוד בשתי הריצות, ולכן אין כאן מה להשוות צורה מול צורה
            lines.append(
                f"[oracle:{name}] הצורות עצמן שונות בין שני התצלומים — המחוללים אינם אותו קוד"
            )
            incomparable.add(name)
            failed = True
            continue
        # ‏``strict`` אינו יכול לזרוק כאן: רשימות הגיבובים שוות, ולכן גם האורכים
        different = [
            index for index, (a, b) in enumerate(zip(before, after, strict=True)) if a != b
        ]
        declared = name in expected
        lines.append(
            f"[oracle:{name}] צורות={len(before)} השתנו={len(different)} "
            f"מסכימות עם cmark: ישן={sum(shape.get('agree') is True for shape in before)} "
            f"חדש={sum(shape.get('agree') is True for shape in after)}"
            + (" — שינוי מוכרז" if declared else "")
        )
        if not different:
            continue
        if declared:
            changed.add(name)
            continue
        failed = True
        for index in different[:_SHOWN]:
            lines.append(f"    #{index} ישן: {before[index]}")
            lines.append(f"    #{index} חדש: {after[index]}")
    for name in expected:
        if name not in changed and name not in incomparable:
            lines.append(f"[oracle:{name}] הוכרז כמשתנה ולא השתנה — ההכרזה אינה מתארת את השדרוג")
            failed = True

    _only_old, _only_new, tokens = _differences(old["info_token_count"], new["info_token_count"])
    lines.append(f"[info_token_count — מידע, לא חלק מפסק הדין] השתנו={len(tokens)}")
    for key in tokens[:_SHOWN]:
        lines.append(f"    {key}: {old['info_token_count'][key]} ← {new['info_token_count'][key]}")

    lines.append("")
    lines.append("פסק דין: " + ("הבדל" if failed else "אפס דיף"))
    print("\n".join(lines))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    snapshot = commands.add_parser("snapshot", help="כותב תצלום JSON של הסביבה הנוכחית")
    # בלי ברירת מחדל, בכוונה: שתי הריצות חייבות לקבל את אותו קורפוס, וברירת מחדל
    # הייתה הופכת את זה להנחה במקום לפקודה שרואים.
    snapshot.add_argument(
        "--root", action="append", required=True, metavar="NAME=PATH",
        help="שורש קורפוס; אפשר כמה. NAME נכנס למפתח של כל קובץ בתצלום",
    )
    snapshot.add_argument("--out", type=Path, required=True, help="קובץ התצלום שייכתב")
    snapshot.add_argument(
        "--family", action="append", default=None,
        help="משפחה באורקל לצילום; אפשר כמה. ברירת מחדל: כולן",
    )

    compare = commands.add_parser("compare", help="משווה שני תצלומים")
    compare.add_argument("old", type=Path, help="התצלום מהסביבה הישנה")
    compare.add_argument("new", type=Path, help="התצלום מהסביבה החדשה")
    compare.add_argument(
        "--expected-change", action="append", default=None, metavar="FAMILY",
        help="משפחה באורקל שצפויה להשתנות בשדרוג; אפשר כמה",
    )

    args = parser.parse_args(argv)
    if args.command == "snapshot":
        return _snapshot(args, parser)
    return _compare(args, parser)


if __name__ == "__main__":
    raise SystemExit(main())
