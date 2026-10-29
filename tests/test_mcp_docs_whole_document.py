"""``whole_document=true`` ב-``codekeeper_docs_get_section`` — הקובץ כולו, דרך ממשק ה-MCP, על מראת git אמיתית.

**למה המצב קיים.** סוכן שקורא לפי טבלת טריגרים מגיע עם **נתיב**, ו-``section`` מחזיר רק
סעיף: מה שלפני הכותרת הראשונה (front matter, הקדמה) אינו באף סעיף, וקובץ עם כמה כותרות
עליונות אינו תת-עץ של אף אחת מהן. ``codekeeper_get_repo_file`` קורא קובץ שלם — לאדמין בלבד.

**האורקל הוא ``codekeeper_get_repo_file``.** מצב מסמך אינו עובד על הטקסט — הוא מגיש את מה
שהקריאה מהמראה החזירה — ולכן ``content`` שלו חייב להיות שווה בית-בית ל-``content`` של כלי
הקבצים על אותו קובץ ו-``ref``: אותה קריאה, אותו פענוח, אותה הסרת BOM. ולכן גם המראה כאן
אמיתית — ``GitMirrorService`` מעל ריפו ``git`` ב-``tmp_path`` — ולא דמה: הפענוח, ה-BOM וה-
``latin-1`` הם של המראה, ודמה הייתה בודקת את עצמה.

הכול דרך ``mcp.call_tool``, עם זהות מטוקן, כמו ``tests/test_mcp_ref_not_mirrored.py``.
"""

from __future__ import annotations

import codecs
import contextlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import types as mcp_types  # noqa: E402
from mcp.server.auth.middleware.auth_context import auth_context_var  # noqa: E402
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser  # noqa: E402
from mcp.server.auth.provider import AccessToken  # noqa: E402
from mcp.server.lowlevel.server import request_ctx  # noqa: E402
from mcp.shared.context import RequestContext  # noqa: E402

import mcp_server.server as srv  # noqa: E402
from mcp_server import docs_handlers  # noqa: E402
from mcp_server.answer_size import OUTPUT_BYTE_BUDGET, wire_json  # noqa: E402
from mcp_server.repo_backend import RepoBackend  # noqa: E402
from services import md_parser  # noqa: E402
from services.git_mirror_service import MAX_FILE_SIZE_FOR_DISPLAY, GitMirrorService  # noqa: E402

_GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(_GIT is None, reason="git is not installed")

_ADMIN = 4242
_USER = 777  # לא ב-ADMIN_USER_IDS: הכלי ציבורי, ומצב מסמך הוא חלק ממנו
_MD = "amir-bug-patterns"  # מדיניות התיעוד: שורש הריפו, .md
_RST = "CodeBot"  # מדיניות התיעוד: docs/, .rst
_TOOL = docs_handlers.SECTION_TOOL_NAME
#: מה ש-``RepoBackend`` מדווח כ-``ref`` כשלא נשלח: הענף הראשי מ-``repo_metadata``, כ-ref מלא.
_DEFAULT_REF = "refs/heads/main"

#: front matter, הקדמה לפני הכותרת הראשונה, ושתי כותרות עליונות — שלושה דברים שאף
#: סעיף אינו מכסה יחד.
_PAGE = (
    "---\ntitle: דף\n---\n\n"
    "הקדמה לפני הכותרת.\n\n"
    "# ראשונה\n\nגוף א.\n\n## תת\n\nגוף תת.\n\n"
    "# שנייה\n\nגוף ב.\n"
)
#: מה ש-``section="ראשונה"`` מחזיר: תת-העץ שלה בלבד (בלי השורה הריקה שלפני הכותרת הבאה).
_FIRST_SUBTREE = "# ראשונה\n\nגוף א.\n\n## תת\n\nגוף תת.\n"
#: ``MAX_LINES`` שורות קצרות הן עשרות KB, ולכן אין צורך להקטין דבר: הסירוב הוא בתצורת הייצור.
#: (``monkeypatch`` על הקבוע לא היה עושה דבר: הוא ברירת המחדל של ``max_lines`` ב-
#: ``md_parser.parse_document``, שנקבעת כשהפונקציה מוגדרת.)
_LONG = "# כותרת\n" + "שורה\n" * md_parser.MAX_LINES
#: ``\r`` בודד — הפורמט של Mac שלפני 2001. הפרסר מסרב (``inconsistent_line_endings``).
_LONE_CR = "# א\n\nשורה\rעם CR בודד\n"
#: עמוד של ``MAX_CHARS_MAX`` תווי CJK הוא פי שלושה בתים, ולכן אינו נכנס ב-``OUTPUT_BYTE_BUDGET``.
_CJK = "# 中\n\n" + "中" * docs_handlers.MAX_CHARS_MAX
#: טקסט ארוך ממספר עמודים ב-``MAX_CHARS_MIN``, עם עברית, CJK ואימוג'י — כדי שגבולות העמודים
#: ייפלו גם בתוך תווים רב-בתיים.
_PAGED = "".join(f"## {i}. סעיף 中文 🙂\n\nשורה {i} של גוף.\n\n" for i in range(120))

_MD_MAIN: dict[str, bytes] = {
    "PAGE.md": _PAGE.encode("utf-8"),
    "BOM.md": codecs.BOM_UTF8 + "# כותרת\n\nגוף עם BOM.\n".encode("utf-8"),
    # לא UTF-8: הפענוח במראה נופל ל-``latin-1``, שמפענח כל רצף בתים.
    "LATIN.md": b"# t\n\n" + "שלום".encode("cp1255") + b"\n",
    "LONG.md": _LONG.encode("utf-8"),
    "CR.md": _LONE_CR.encode("utf-8"),
    "CJK.md": _CJK.encode("utf-8"),
    "PAGED.md": _PAGED.encode("utf-8"),
    "BIG.md": b"x" * (MAX_FILE_SIZE_FOR_DISPLAY + 1),
}
_MD_FEATURE: dict[str, bytes] = {"PAGE.md": "# גרסת feature\n\nאחרת.\n".encode("utf-8")}
#: עמוד RST עם תווית לפני הכותרת — גם היא אינה בשום סעיף.
_GUIDE_RST = ".. _guide:\n\nGuide\n=====\n\nIntro.\n"


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run((_GIT, *args), cwd=str(cwd), check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _commit(work: Path, files: dict[str, bytes], message: str) -> None:
    for name, body in files.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    _git("add", "-A", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message, cwd=work)


def _repo(tmp_path: Path, name: str, files: dict[str, bytes]) -> Path:
    work = tmp_path / "work" / name
    work.mkdir(parents=True)
    _git("init", "-q", "-b", "main", ".", cwd=work)
    # בלי המרות שורה של git — הבתים שנכתבו הם הבתים שנשמרים.
    _git("config", "core.autocrlf", "false", cwd=work)
    _commit(work, files, "init")
    return work


class _Collection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    def find_one(self, query: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None


@dataclass
class _World:
    mcp: Any
    main_sha: str
    feature_sha: str


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _World:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MCP_DOCS_REPO", f"{_MD},{_RST}")
    monkeypatch.setenv("REPO_MIRROR_PATH", str(tmp_path / "unused-default"))
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "ADMIN_USER_IDS", [_ADMIN], raising=False)

    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    md_work = _repo(tmp_path, _MD, _MD_MAIN)
    _git("checkout", "-q", "-b", "feature", cwd=md_work)
    _commit(md_work, _MD_FEATURE, "feature")
    _git("checkout", "-q", "main", cwd=md_work)
    rst_work = _repo(tmp_path, _RST, {"docs/guide.rst": _GUIDE_RST.encode("utf-8")})
    for name, work in ((_MD, md_work), (_RST, rst_work)):
        _git("clone", "-q", "--mirror", str(work), str(mirrors / f"{name}.git"), cwd=tmp_path)

    db = {
        "repo_metadata": _Collection([{"repo_name": n, "default_branch": "main"} for n in (_MD, _RST)]),
        "sync_jobs": _Collection([]),
    }
    backend = RepoBackend(db=db, mirror=GitMirrorService(base_path=str(mirrors)))
    return _World(
        srv.build_mcp(object(), repo_backend=backend),
        main_sha=_git("rev-parse", "main", cwd=md_work),
        feature_sha=_git("rev-parse", "feature", cwd=md_work),
    )


@contextlib.contextmanager
def _as(user: int):
    request_token = request_ctx.set(RequestContext(request_id=1, meta=None, session=None, lifespan_context=None))
    access = AccessToken(token="t", client_id="c", scopes=["read"], subject=str(user))
    auth_token = auth_context_var.set(AuthenticatedUser(access))
    try:
        yield
    finally:
        auth_context_var.reset(auth_token)
        request_ctx.reset(request_token)


async def _sent(mcp: Any, name: str, arguments: dict[str, Any], *, user: int = _ADMIN) -> tuple[dict, int]:
    """התשובה, **ומספר הבתים שלה כפי שה-SDK שלח אותה** — בלוק הטקסט עצמו, לא הערכה."""
    with _as(user):
        result = await mcp.call_tool(name, arguments)
    content = result.content if isinstance(result, mcp_types.CallToolResult) else result
    if isinstance(content, tuple):
        content = content[0]
    (block,) = content
    return json.loads(block.text), len(block.text.encode("utf-8"))


async def _call(mcp: Any, name: str, arguments: dict[str, Any], *, user: int = _ADMIN) -> dict:
    return (await _sent(mcp, name, arguments, user=user))[0]


async def _document(mcp: Any, *, user: int = _ADMIN, **arguments: Any) -> dict:
    return await _call(mcp, _TOOL, {"repo": _MD, "whole_document": True, **arguments}, user=user)


async def _repo_file(mcp: Any, path: str, **arguments: Any) -> dict:
    return await _call(mcp, "codekeeper_get_repo_file", {"repo": _MD, "path": path, **arguments})


async def _all_pages(mcp: Any, *, path: str, max_chars: int, user: int = _ADMIN) -> list[dict]:
    """כל העמודים של מצב מסמך, מ-``offset=0`` ועד ש-``truncated`` כבה."""
    pages = [await _document(mcp, path=path, max_chars=max_chars, user=user)]
    while pages[-1]["truncated"]:
        assert len(pages) < 10_000, "next_offset אינו מתקדם"
        pages.append(await _document(mcp, path=path, max_chars=max_chars, user=user,
                                     offset=pages[-1]["next_offset"]))
    return pages


# ---- הטקסט: האורקל ----


@pytest.mark.parametrize("path, ref", [
    ("PAGE.md", None),
    ("PAGE.md", "feature"),
    ("BOM.md", None),
    ("LATIN.md", None),
    ("LONG.md", None),
    ("CR.md", None),
])
async def test_the_document_is_byte_for_byte_what_get_repo_file_returns(world, path, ref):
    """``content`` שווה בית-בית ל-``content`` של ``codekeeper_get_repo_file`` — ואותו ``file``.

    על כל צורת קריאה שהמראה מבדילה: UTF-8 רגיל, ענף אחר (``ref``), BOM (המראה מסירה
    אותו, ``utf-8-sig``), ו-``latin-1`` (הנפילה-לאחור). גם ``ref``, ``resolved_commit``
    ו-``encoding`` הם אלה של הקריאה — אותה קריאה, ולא שתיים שבמקרה מסכימות.

    מוטציה שמפילה: לבנות את ``content`` מהשורות של הפרסר — ה-BOM חוזר, וקובץ שהפרסר
    מסרב לו אינו נקרא כלל.
    """
    refs = {"ref": ref} if ref else {}
    oracle = await _repo_file(world.mcp, path, **refs)
    assert oracle["ok"] and oracle["status"] == "ok", "הנחת המקרה"

    out = await _document(world.mcp, path=path, max_chars=docs_handlers.MAX_CHARS_MAX, **refs)

    assert out["content"] == oracle["content"]
    assert out["truncated"] is False
    assert (out["ref"], out["resolved_commit"], out["encoding"]) == (
        oracle["file"]["ref"], oracle["file"]["resolved_commit"], oracle["file"]["encoding"])


async def test_the_answer_has_the_document_shape_and_nothing_a_parse_would_give(world):
    """הצורה של תשובת מסמך: מה יש בה, ומה **אין** בה כי אין פרסור.

    ``max_chars`` מהודהד כפי שנאכף (``100`` נצמד ל-``MAX_CHARS_MIN``). ``breadcrumb``,
    ``subsections``, ``neighbors``, ``includes`` ו-``section_count`` הם תוצרים של פרסור,
    ושדה שהיה מופיע כאן ריק היה מלמד את הקורא שיש להם ערך במצב הזה.
    """
    assert len(_PAGE) < docs_handlers.MAX_CHARS_MIN, "הנחת המקרה: עמוד אחד"
    out = await _document(world.mcp, path="PAGE", max_chars=100)

    assert out == {
        "ok": True, "repo": _MD, "path": "PAGE.md", "ref": _DEFAULT_REF,
        "resolved_commit": world.main_sha, "mode": "document", "encoding": "utf-8",
        "max_chars": docs_handlers.MAX_CHARS_MIN, "offset": 0, "content": _PAGE,
        "truncated": False,
    }


async def test_latin_1_is_reported_as_the_label_the_mirror_gave(world):
    """``encoding: latin-1`` — התווית של הנפילה-לאחור, כמו ב-``codekeeper_get_repo_file``.

    ``latin-1`` מפענח כל רצף בתים, ולכן הוא אזהרה ולא זיהוי: ``שלום`` ב-``cp1255`` חוזר
    משובש. התשובה אומרת את זה בשדה, ולא מציגה טקסט משובש כאילו הוא תקין.
    """
    out = await _document(world.mcp, path="LATIN")

    assert out["encoding"] == "latin-1"
    assert "שלום" not in out["content"]


# ---- העימוד ----


async def test_pages_join_into_the_whole_text_with_nothing_missing_or_doubled(world):
    """``max_chars=MAX_CHARS_MIN``: העמודים מצטרפים לטקסט המלא — בלי תו חסר ובלי כפול.

    בכל עמוד ``next_offset`` הוא בדיוק סוף העמוד, ו-``remaining_chars`` הוא מה שנשאר
    עד הסוף; בעמוד האחרון שניהם אינם. הטקסט מעורב עברית, CJK ואימוג'י, כך שגבולות
    העמודים נופלים גם בתוך תווים רב-בתיים — והחיתוך הוא על גבול תו.

    מוטציה שמפילה: ``offset`` שאינו מוחל (כל עמוד מתחיל מ-0) — העמוד השני חוזר על
    הראשון.
    """
    pages = await _all_pages(world.mcp, path="PAGED", max_chars=docs_handlers.MAX_CHARS_MIN)

    assert len(pages) > 2, "הנחת המקרה: כמה עמודים"
    assert "".join(page["content"] for page in pages) == _PAGED
    for page in pages[:-1]:
        end = page["offset"] + len(page["content"])
        assert len(page["content"]) == docs_handlers.MAX_CHARS_MIN
        assert (page["truncated"], page["next_offset"], page["remaining_chars"]) == (
            True, end, len(_PAGED) - end)
        assert "truncation_reason" not in page
    assert pages[-1]["truncated"] is False
    assert {"next_offset", "remaining_chars", "truncation_reason"}.isdisjoint(pages[-1])


async def test_a_cjk_page_that_does_not_fit_ends_early_on_byte_budget(world):
    """עמוד של ``MAX_CHARS_MAX`` תווי CJK נגמר מוקדם, על ``byte_budget`` — ואינו מאבד תו.

    התשובה **כפי שנשלחה** נכנסת ב-``OUTPUT_BYTE_BUDGET``, והעמוד הוא **הארוך ביותר**
    שנכנס: תו אחד נוסף — עם ``remaining_chars`` ו-``next_offset`` שזזים איתו — כבר עובר
    את התקציב. זה החוזה של ``_fit_page``, ושום עימוד אחר אינו מקיים אותו במקרה.

    מוטציה שמפילה: עימוד שני במצב מסמך במקום ``_text_page`` — למשל תקרה של שליש
    התקציב בתווים, "כי CJK הוא שלושה בתים" — העמוד קצר מהמקסימום.
    """
    out, sent = await _sent(world.mcp, _TOOL, {"repo": _MD, "path": "CJK", "whole_document": True,
                                               "max_chars": docs_handlers.MAX_CHARS_MAX})

    assert sent <= OUTPUT_BYTE_BUDGET
    assert out["truncated"] is True and out["truncation_reason"] == "byte_budget"
    assert len(out["content"]) < docs_handlers.MAX_CHARS_MAX
    assert out["content"] == _CJK[:len(out["content"])]
    assert out["next_offset"] == len(out["content"])
    assert out["remaining_chars"] == len(_CJK) - len(out["content"])

    one_more = {**out, "content": _CJK[:out["next_offset"] + 1],
                "remaining_chars": out["remaining_chars"] - 1,
                "next_offset": out["next_offset"] + 1}
    assert len(wire_json(one_more)) > OUTPUT_BYTE_BUDGET

    rest = await _document(world.mcp, path="CJK", max_chars=docs_handlers.MAX_CHARS_MAX,
                           offset=out["next_offset"])
    assert out["content"] + rest["content"] == _CJK
    assert rest["truncated"] is False


# ---- מה שסעיף אינו מגיע אליו ----


async def test_front_matter_and_both_top_level_headings_are_in_the_document_and_not_in_a_section(world):
    """מצב מסמך מחזיר את ה-``---``, את ההקדמה ואת שתי הכותרות; ``section`` — רק תת-עץ אחד.

    זה הפער שהמצב בא לסגור: "הכותרת הראשונה היא הקובץ" אינו נכון לקובץ כזה, ומי שאינו
    אדמין לא יכול היה לקרוא את מה שלפני הכותרת הראשונה בשום דרך.
    """
    document = await _document(world.mcp, path="PAGE", user=_USER)
    section = await _call(world.mcp, _TOOL, {"repo": _MD, "path": "PAGE", "section": "ראשונה"},
                          user=_USER)

    assert document["content"] == _PAGE
    assert section["content"] == _FIRST_SUBTREE
    for outside_the_section in ("---\ntitle", "הקדמה לפני הכותרת", "# שנייה"):
        assert outside_the_section in document["content"]
        assert outside_the_section not in section["content"]


async def test_an_rst_page_is_read_whole_with_its_label_before_the_title(world):
    """אותו מצב בעמוד RST: התווית שלפני הכותרת היא חלק מהמסמך — ואין ``includes``."""
    out = await _call(world.mcp, _TOOL, {"repo": _RST, "path": "guide", "whole_document": True})

    assert out["mode"] == "document" and out["path"] == "docs/guide.rst"
    assert out["content"] == _GUIDE_RST
    assert "includes" not in out


@pytest.mark.parametrize("path, refusal", [
    ("LONG", "too_many_lines"),
    ("CR", "inconsistent_line_endings"),
])
async def test_a_file_the_parser_refuses_is_still_read_whole(world, path, refusal):
    """קובץ שמפת הכותרות מסרבת לו נקרא שלם במצב מסמך — כי אין בו פרסור.

    ``too_many_lines`` בתצורת הייצור (``MAX_LINES`` שורות קצרות), ו-``\\r`` בודד. היום
    ההפניה בסירובים האלה היא ``codekeeper_get_repo_file`` עם ``lines`` — שאינו זמין למי
    שאינו אדמין — ולכן הבדיקה רצה כמשתמש רגיל.

    מוטציה שמפילה: לפרסר גם במצב מסמך (``load_document`` במקום ``load_text``) — הסירוב
    חוזר.
    """
    refused = await _call(world.mcp, _TOOL, {"repo": _MD, "path": path}, user=_USER)
    assert refused["error"] == refusal, "הנחת המקרה: מפת הכותרות מסרבת"

    pages = await _all_pages(world.mcp, path=path, max_chars=docs_handlers.MAX_CHARS_MAX, user=_USER)

    assert all(page["ok"] and page["mode"] == "document" for page in pages)
    assert "".join(page["content"] for page in pages) == (await _repo_file(world.mcp, f"{path}.md"))["content"]


async def test_include_subsections_changes_nothing_in_a_document(world):
    """``include_subsections`` אין לו משמעות במצב מסמך — ואי אפשר לדעת אם נשלח, ולכן אין סירוב."""
    assert (await _document(world.mcp, path="PAGE", include_subsections=False)
            == await _document(world.mcp, path="PAGE"))


# ---- השער: מה שנקרא היום, ורק הוא ----


@pytest.mark.parametrize("arguments, error", [
    ({"path": "secrets"}, "path_denied"),
    ({"path": "guide.rst"}, "suffix_not_allowed"),
    ({"path": "../outside"}, "path_outside_root"),
    ({"path": "NOPE"}, "not_found"),
    ({"path": "NOPE", "ref": "feature"}, "not_found"),
    ({"path": "BIG"}, "unreadable_too_large"),
    ({"path": "PAGE", "repo": "not-allowed"}, "repo_not_allowed"),
])
async def test_every_refusal_is_the_one_section_mode_gives(world, arguments, error):
    """כל סירוב של מצב מסמך זהה לסירוב של אותו קובץ במצב סעיף — אותה קריאה, אותו שער.

    זה הכלל שהופך את המצב לבטוח בכלי ציבורי: שום קובץ שלא נקרא היום סעיף-סעיף אינו
    נקרא עכשיו. מדיניות הנתיבים, מדיניות הסודות, הריפו, ``ref`` ותקרת ה-500KB. ו-
    ``not_found`` נושא את ``ref`` ואת ``resolved_commit`` — איפה חיפשו.
    """
    arguments = {"repo": _MD, **arguments}
    section_mode = await _call(world.mcp, _TOOL, arguments, user=_USER)
    assert section_mode["ok"] is False and section_mode["error"] == error, "הנחת המקרה"

    document_mode = await _call(world.mcp, _TOOL, {**arguments, "whole_document": True}, user=_USER)

    assert document_mode == section_mode
    if error == "not_found":
        expected = world.feature_sha if arguments.get("ref") == "feature" else world.main_sha
        assert (document_mode["ref"], document_mode["resolved_commit"]) == (
            arguments.get("ref", _DEFAULT_REF), expected)


@pytest.mark.parametrize("arguments, error", [
    ({"section": "ראשונה"}, docs_handlers.SECTION_AND_WHOLE_DOCUMENT),
    ({"section": ""}, docs_handlers.SECTION_AND_WHOLE_DOCUMENT),
    ({"max_depth": 2}, docs_handlers.MAX_DEPTH_AND_WHOLE_DOCUMENT),
    ({"section": "ראשונה", "max_depth": 2}, docs_handlers.SECTION_AND_WHOLE_DOCUMENT),
    ({"section": "ראשונה", "repo": "not-allowed"}, docs_handlers.SECTION_AND_WHOLE_DOCUMENT),
])
async def test_a_parameter_that_would_be_dropped_is_refused_by_its_name(world, arguments, error):
    """``section`` או ``max_depth`` עם ``whole_document`` — סירוב בשם הפרמטר, ולא התעלמות.

    ``section`` נבדק ראשון כשנשלחו שניהם, ו-``section=""`` נשלח גם הוא. והסירוב קודם
    לשאלת הריפו: צירוף פסול פסול בלי קשר לקובץ, ו-``repo_not_allowed`` היה שולח את
    הקורא לתקן ריפו במקום קריאה.

    מוטציה שמפילה: להסיר את ההדרה — ``section`` נזרק בשקט והקובץ כולו חוזר.
    """
    out = await _document(world.mcp, path="PAGE", **arguments)

    assert out == {"ok": False, "error": error}


@pytest.mark.parametrize("sent, mode", [("true", "document"), ("false", "toc")])
async def test_the_flag_sent_as_a_string_is_read_as_the_caller_meant(world, sent, mode):
    """``whole_document="true"`` הוא ``true``, ו-``"false"`` הוא ``false`` — כמו ``toc``.

    ``bool`` רגיל בסכימה: ``pre_parse_json`` של ה-SDK משאיר את המחרוזת, והוולידציה
    ממירה אותה (ההערה מעל ``StrictInt`` ב-``mcp_server/handlers.py``).
    """
    out = await _call(world.mcp, _TOOL, {"repo": _MD, "path": "PAGE", "whole_document": sent})

    assert out["mode"] == mode


async def test_without_the_flag_every_answer_is_what_it_was(world):
    """``whole_document=false`` שנשלח במפורש — אותה תשובה כמו בלי הפרמטר, בכל צורה.

    ברירת המחדל היא התשובה של לפני הפרמטר; המפה, הסעיף, והסירוב של ``section_not_found``
    לא זזים. (ההוכחה הרחבה — כל הטסטים הקיימים של הכלי עוברים בלי שינוי, ו-
    ``scripts/docs_section_zero_diff.py`` על כל קורפוס ה-RST.)
    """
    for extra in ({}, {"section": "ראשונה"}, {"section": "אין כזה"}, {"max_depth": 1}):
        arguments = {"repo": _MD, "path": "PAGE", **extra}
        assert (await _call(world.mcp, _TOOL, {**arguments, "whole_document": False})
                == await _call(world.mcp, _TOOL, arguments))


# ---- סירוב תקציב שאינו נגיש ממראה אמיתית ----


class _HugeRefBackend:
    """``RepoBackend.get_file`` שמחזיר ``file.ref`` באורך שגדול מהתקציב לבדו.

    ממראה אמיתית זה דורש ``ref`` שהקורא שלח ו-git פתר, בגודל של מאות KB — ולכן דמה.
    הענף עצמו קיים בקוד, כי ``_fit_page`` מחזיר ``None`` כשגם תו אחד אינו נכנס.
    """

    def get_file(self, *, repo, path, ref=None):
        return {"ok": True, "status": "ok",
                "file": {"path": path, "ref": "r" * OUTPUT_BYTE_BUDGET, "resolved_commit": "c0ffee",
                         "encoding": "utf-8"},
                "content": "# כותרת\n\nגוף\n"}


def test_a_page_that_cannot_carry_one_character_is_answer_too_large_and_not_an_empty_page(monkeypatch):
    """הקשר גדול מהתקציב — ``answer_too_large`` עם ``bytes > max``, ולא עמוד ריק.

    עמוד ריק עם ``next_offset`` שאינו זז היה שולח קורא ממושמע ללולאה אינסופית. ``bytes``
    הוא מה שהעמוד הקטן ביותר שנושא תוכן היה צריך, ו-``max`` הוא ``OUTPUT_BYTE_BUDGET``.

    מוטציה שמפילה: להחזיר את ``page`` בלי לבדוק ``None`` — ``None`` חוזר כתשובה.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", _MD)
    out = docs_handlers.docs_get_section(_HugeRefBackend(), path="x", whole_document=True)

    assert out["ok"] is False and out["error"] == "answer_too_large"
    assert out["max"] == OUTPUT_BYTE_BUDGET and out["bytes"] > out["max"]
    assert (out["repo"], out["path"]) == (_MD, "x.md")
    assert "content" not in out


# ---- מה שהסוכן קורא ----


async def test_the_descriptions_lead_a_path_holder_to_the_whole_document_mode(world):
    """תיאור הכלי מפנה לקובץ שלם בלי "הכותרת הראשונה", ותיאור הפרמטר נפתח במתי.

    "pass its title (the first TOC entry) as section" כבר אינו נכון לכל קובץ — ולכן אסור
    שיחזור. תיאור הפרמטר נפתח ב"מתי" (לקוח מקצר תיאור פרמטר לכ-120 תווים), והקודים
    והמספרים בו נשתלים מהקבועים.
    """
    tool = world.mcp._tool_manager.get_tool(_TOOL)
    doc = tool.parameters["properties"]["whole_document"]["description"]

    assert "whole_document=true" in tool.description
    assert "codekeeper_read_batch" in tool.description
    assert "first TOC entry" not in tool.description
    assert doc.startswith("When you came with a path and not a heading")
    for stated in (docs_handlers.SECTION_AND_WHOLE_DOCUMENT, docs_handlers.MAX_DEPTH_AND_WHOLE_DOCUMENT,
                   f"default {docs_handlers.MAX_CHARS_DEFAULT}", f"{OUTPUT_BYTE_BUDGET} bytes",
                   f"{MAX_FILE_SIZE_FOR_DISPLAY // 1024}KB"):
        assert stated in doc, stated
