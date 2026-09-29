"""השומר על בלוק ה-``instructions`` של השרת: מה שהסוכן רואה בתחילת הסשן מול מה שבאמת רשום.

**למה השומר קיים.** הבלוק הוא מה שהסוכן רואה לפני שהוא יודע איזה כלי לחפש — עם טעינת
כלים מושהית, רק השמות והבלוק נטענים בתחילת הסשן. הגרסה הקודמת שלו לא הזכירה חלק גדול
מהכלים, ואיש לא ידע, כי שום דבר לא השווה אותו לרישום. מכאן הכלל: **מי שמוסיף כלי מוסיף
אותו גם לבלוק**, ואחרת הטסט כאן נופל.

**ומה נבדק הוא מה שהלקוח מעביר, לא הבלוק כולו.** Claude Code חותך את הבלוק ב-
``CLIENT_INSTRUCTIONS_MAX_CHARS`` תווים (ההערה שם נוקבת במקור ובתאריך), ולכן השמות
נשלפים מ-``instructions[:CLIENT_INSTRUCTIONS_MAX_CHARS]``. טיוטה של הבלוק נשאה את כל 32
השמות — והסוכן היה רואה 21 מהם. בדיקה על הבלוק המלא הייתה ירוקה על זה.

**דרך הממשק, לא דרך פונקציה פנימית** (``TESTING-PATTERNS`` T1): כל הקריאות כאן עוברות
ב-session אמיתי של הפרוטוקול מול ``build_mcp`` — ``initialize`` נותן את הבלוק כפי שהלקוח
מקבל אותו, ו-``tools/list`` את הכלים כפי שהלקוח רואה אותם, כולל הכלי הווירטואלי ש-
PostHog מוסיף **אחרי** הסינון של כלי האדמין. **ובתצורת הייצור** (T1 וריאציה e): PostHog
דלוק (לקוח אמיתי עם ``send=False``, שום דבר לא יוצא לרשת), רשימת הריפואים של הייצור,
ומראה — הבלוק הארוך ביותר שנשלח בפועל.
"""

from __future__ import annotations

import logging
import re

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.shared.memory import create_client_server_memory_streams  # noqa: E402

from mcp_server import analytics, docs_handlers  # noqa: E402
from mcp_server import server as srv  # noqa: E402

#: ``MCP_DOCS_REPO`` של שירות ה-MCP בייצור. **אינו רשום בריפו** — ``render.yaml`` אינו
#: מגדיר אותו, וברירת המחדל בקוד היא ``CodeBot`` בלבד — ולכן הוא כתוב כאן, ומקורו בעל
#: הפרויקט (2026-09-29). פריסה שתשנה אותו אינה נראית לטסט; מה שמכסה אותה הוא האזהרה
#: בעליית השרת (``_warn_if_instructions_exceed_cap``).
PRODUCTION_DOCS_REPOS = "CodeBot,amir-bug-patterns"

#: כלים ש-``tools/list`` מחזיר ואין חובה לנקוב בהם בבלוק, או להפך — **שם ← הנימוק**.
#: ריק היום: הכלי הווירטואלי של PostHog אינו חריג, כי המשפט עליו נבנה רק כשהוא באמת
#: ברשימה, והוא נבדק בנפרד. מי שמוסיף כאן שם כותב לידו למה.
EXCLUDED: dict[str, str] = {}

_TOOL_NAME = re.compile(r"codekeeper_\w+")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


class _Backend:
    """אף גוף כלי אינו רץ כאן — הרישום בלבד."""


class _RepoBackend:
    """``repo_backend`` קיים, כדי שכלי המראה והתיעוד יירשמו כמו בייצור."""


@pytest.fixture
def posthog_client():
    """לקוח ``Posthog`` אמיתי שאינו שולח — אותה תצורה כמו ב-``tests/test_mcp_pre_parse_json.py``."""
    from posthog import Posthog

    client = Posthog(
        "phc_test_token_not_real",
        host="https://us.i.posthog.com",
        send=False,
        before_send=analytics.scrub_mcp_payload,
        enable_exception_autocapture=False,
        capture_exception_code_variables=False,
    )
    try:
        yield client
    finally:
        client.shutdown()


def _build(monkeypatch, *, posthog=None, repos=PRODUCTION_DOCS_REPOS, **kwargs):
    """``build_mcp`` אמיתי. ``posthog`` הוא לקוח (מדידה דלוקה) או ``None`` (כבויה)."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MCP_DOCS_REPO", repos)
    monkeypatch.setattr(analytics, "_CLIENT", posthog)
    monkeypatch.setattr(analytics, "_ANALYTICS", None)
    return srv.build_mcp(_Backend(), repo_backend=_RepoBackend(), **kwargs)


async def _client_view(mcp, monkeypatch, *, admin: bool) -> tuple[str, set[str]]:
    """``(instructions, names)`` כפי שלקוח מקבל אותם: ``initialize`` ואז ``tools/list``.

    ``_request_is_admin`` מוחלף, כמו בשאר טסטי הרישום — ה-session בזיכרון אינו נושא
    טוקן. הזהות עצמה נבדקת ב-``tests/test_mcp_require_admin.py``.
    """
    monkeypatch.setattr(mcp, "_request_is_admin", lambda: admin)
    server = mcp._mcp_server
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_streams[0],
                    server_streams[1],
                    server.create_initialization_options(),
                    raise_exceptions=True,
                )
            )
            async with ClientSession(client_streams[0], client_streams[1]) as session:
                initialized = await session.initialize()
                listed = {tool.name for tool in (await session.list_tools()).tools}
            tg.cancel_scope.cancel()
    await analytics._drain()
    return initialized.instructions or "", listed


def _visible(instructions: str) -> str:
    """מה שהלקוח מעביר לסוכן מתוך הבלוק."""
    return instructions[: srv.CLIENT_INSTRUCTIONS_MAX_CHARS]


def _uncovered(instructions: str, listed: set[str]) -> set[str]:
    """ההפרש הסימטרי בין השמות שבתוך התקרה לכלים שב-``tools/list``, בלי החריגים."""
    named = set(_TOOL_NAME.findall(_visible(instructions)))
    tools = {name for name in listed if _TOOL_NAME.fullmatch(name)}
    return (named ^ tools) - set(EXCLUDED)


async def test_every_tool_the_admin_lists_is_named_within_the_client_cap(
        monkeypatch, posthog_client):
    """הכיסוי, בתצורת הייצור: כל כלי שאדמין רואה נקוב בבלוק, **בתוך התקרה**, ולהפך."""
    mcp = _build(monkeypatch, posthog=posthog_client)
    instructions, listed = await _client_view(mcp, monkeypatch, admin=True)

    uncovered = _uncovered(instructions, listed)
    assert not uncovered, (
        "הבלוק ו-tools/list של אדמין אינם מסכימים (בתוך "
        f"{srv.CLIENT_INSTRUCTIONS_MAX_CHARS} התווים שהלקוח מעביר): {sorted(uncovered)}. "
        "כלי חדש נכנס גם ל-build_instructions ב-mcp_server/server.py; שם בבלוק שאינו "
        "רשום הוא הבטחה לכלי שאינו קיים."
    )


async def test_the_block_fits_the_client_cap_in_the_production_configuration(
        monkeypatch, posthog_client):
    """התקרה עצמה: מה שמעבר לה אינו מגיע לסוכן, גם כשאינו שם של כלי."""
    mcp = _build(monkeypatch, posthog=posthog_client)
    instructions, _listed = await _client_view(mcp, monkeypatch, admin=True)

    assert len(instructions) <= srv.CLIENT_INSTRUCTIONS_MAX_CHARS, (
        f"הבלוק {len(instructions)} תווים, והלקוח מעביר "
        f"{srv.CLIENT_INSTRUCTIONS_MAX_CHARS}: הסוף נחתך בשקט. "
        f"מה שנחתך: {instructions[srv.CLIENT_INSTRUCTIONS_MAX_CHARS:]!r}"
    )


async def test_the_virtual_tool_is_named_exactly_when_it_is_listed(
        monkeypatch, posthog_client):
    """הכלי הווירטואלי של PostHog: נקוב בבלוק אם ורק אם ``tools/list`` מחזיר אותו.

    הוא מתווסף אחרי הרישום ולכן אינו ב-``_tool_manager`` — מה שנבדק הוא מה שהלקוח
    רואה מעבר לכלים הרשומים.
    """
    mcp_on = _build(monkeypatch, posthog=posthog_client)
    registered_on = {t.name for t in mcp_on._tool_manager.list_tools()}
    instructions_on, listed_on = await _client_view(mcp_on, monkeypatch, admin=True)
    extra_on = listed_on - registered_on
    assert extra_on == {analytics.MISSING_CAPABILITY_TOOL_NAME}, extra_on
    assert analytics.MISSING_CAPABILITY_TOOL_NAME in _IDENTIFIER.findall(_visible(instructions_on))

    mcp_off = _build(monkeypatch, posthog=None)
    instructions_off, listed_off = await _client_view(mcp_off, monkeypatch, admin=True)
    registered_off = {t.name for t in mcp_off._tool_manager.list_tools()}
    assert listed_off == registered_off
    assert analytics.MISSING_CAPABILITY_TOOL_NAME not in _IDENTIFIER.findall(instructions_off)
    # ובלי המדידה הכיסוי עדיין מלא — המשפט הוא התוספת היחידה.
    assert not _uncovered(instructions_off, listed_off)


async def test_a_silently_failed_instrumentation_does_not_name_the_virtual_tool(
        monkeypatch, posthog_client):
    """K11: ``instrument()`` אינו זורק בכשל — הוא מחזיר ידית ריקה. הבלוק נשען על מה שהותקן."""
    import posthog.mcp

    def _degraded(server, client=None, options=None):
        return posthog.mcp._NoopAnalytics()

    monkeypatch.setattr(posthog.mcp, "instrument", _degraded)
    mcp = _build(monkeypatch, posthog=posthog_client)
    instructions, listed = await _client_view(mcp, monkeypatch, admin=True)

    assert analytics.MISSING_CAPABILITY_TOOL_NAME not in listed
    assert analytics.MISSING_CAPABILITY_TOOL_NAME not in _IDENTIFIER.findall(instructions)


async def test_the_admin_group_names_exactly_what_other_users_do_not_see(
        monkeypatch, posthog_client):
    """"Repos (admins only)" היא טענה על ההרשאות — והיא נבדקת מול מה שהשרת באמת מסתיר.

    כלי האדמין **נגזרים מהממשק** — ``tools/list`` של אדמין פחות זה של משתמש רגיל — ולא
    מרשימת שמות: רשימה היא מקום שני לסנכרן.
    """
    mcp = _build(monkeypatch, posthog=posthog_client)
    instructions, admin_listed = await _client_view(mcp, monkeypatch, admin=True)
    _same, user_listed = await _client_view(mcp, monkeypatch, admin=False)
    admin_only = admin_listed - user_listed
    assert admin_only, "תצוגת האדמין זהה לתצוגה הרגילה — הטסט איבד את מה שהוא משווה"

    groups = _visible(instructions).split("\n\n")
    admin_groups = [g for g in groups if "(admins only)" in g.split("\n", 1)[0]]
    assert len(admin_groups) == 1, groups
    assert set(_TOOL_NAME.findall(admin_groups[0])) == admin_only
    for group in groups:
        if group is not admin_groups[0]:
            assert not set(_TOOL_NAME.findall(group)) & admin_only, group


@pytest.mark.parametrize(
    ("repos", "sentence"),
    [
        (PRODUCTION_DOCS_REPOS, "It serves CodeBot and amir-bug-patterns."),
        ("amir-bug-patterns", "It serves amir-bug-patterns."),
        # מותר בסביבה ואין לו מדיניות ← הכלי מסרב לו, ולכן הוא אינו "מוגש".
        ("CodeBot,ghost-repo", "It serves CodeBot."),
    ],
)
async def test_the_docs_sentence_names_what_the_docs_tool_serves(monkeypatch, repos, sentence):
    """שורת התיעוד נגזרת מ-``MCP_DOCS_REPO`` ומטבלת המדיניות, ולא מוקלדת."""
    mcp = _build(monkeypatch, repos=repos)
    instructions, _listed = await _client_view(mcp, monkeypatch, admin=False)

    assert sentence in instructions
    assert docs_handlers.served_docs_repos() == [r for r in repos.split(",") if r != "ghost-repo"]


async def test_the_batch_size_is_the_cap_this_server_enforces(monkeypatch):
    """"up to N" הוא התקרה שהשרת הזה אוכף (``batch_item_cap``), ולא מספר מוקלד."""
    mcp = _build(monkeypatch, rate_limit_per_minute=5)
    instructions, _listed = await _client_view(mcp, monkeypatch, admin=True)

    assert mcp.batch_item_cap() == 5
    assert "codekeeper_read_batch reads up to 5 sections" in instructions


async def test_a_block_over_the_cap_warns_with_the_tool_names_it_loses(monkeypatch, caplog):
    """האזהרה בעליית השרת נוקבת בשמות שנפלו מעבר לתקרה — מה שהלקוח חותך בשקט.

    ריפואים סינתטיים בשמות ארוכים מאריכים את שורת התיעוד עד שקבוצת האדמין, האחרונה
    בבלוק, נדחקת מעבר לתקרה. ``caplog`` כאן בודק **תוכן** של שורה, לא את השאלה אם
    לוגים נראים בכלל — זו ``tests/test_mcp_logging_visible.py``.
    """
    long_names = [f"synthetic-docs-repository-{i:02d}-with-a-long-name" for i in range(12)]
    for name in long_names:
        monkeypatch.setitem(docs_handlers._DOCS_PATH_POLICY_TABLE, name,
                            docs_handlers._DocsPathPolicy(root="", suffix=".md"))
    caplog.set_level(logging.WARNING, logger="mcp_server.server")

    mcp = _build(monkeypatch, repos=",".join(long_names))
    instructions, listed = await _client_view(mcp, monkeypatch, admin=True)
    named = set(_TOOL_NAME.findall(instructions))
    lost = sorted(named - set(_TOOL_NAME.findall(_visible(instructions))))

    assert lost, "הבלוק לא נדחק מעבר לתקרה — הטסט אינו בודק את מה שהוא מתיימר"
    warnings = [r.getMessage() for r in caplog.records if "past the cut" in r.getMessage()]
    assert len(warnings) == 1, warnings
    for name in lost:
        assert name in warnings[0], (name, warnings[0])
    # והשומר רואה אותם בדיוק כמו האזהרה: כל שם שנפל הוא כלי שאינו מכוסה.
    assert set(lost) <= _uncovered(instructions, listed)
