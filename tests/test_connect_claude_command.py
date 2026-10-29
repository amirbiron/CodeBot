"""``/connect_claude`` — פקודת החיבור שהבוט מחזיר ל-Claude Code.

הפקודה נבנית ב-``connect_claude_command`` ב-``main.py``. בלי ``--scope``, ``claude mcp add``
שומר ב-scope ברירת המחדל, ``local``: ב-``~/.claude.json`` תחת הרשומה של הפרויקט שממנו הורצה
(``projects`` ← נתיב הפרויקט ← ``mcpServers``), ו-CodeKeeper היה זמין רק בתיקייה ההיא. עם
``--scope user`` הרשומה נכתבת ל-``mcpServers`` שבראש הקובץ וזמינה בכל הפרויקטים — וזה מה
שמאגר אישי צריך. המקור: ``code.claude.com/docs/en/mcp``, ה-Tips של ``--scope`` (נקרא
ב-2026-10-29), ונמדד באותו יום ב-Claude Code 2.1.312 בתיקיית הגדרות מבודדת: בלי הדגל
הרשומה נכתבה תחת ``projects``, ועם הדגל — בראש הקובץ, ו-``claude mcp get`` מפרויקט אחר
דיווח "User config (available in all your projects)". ה-CI אינו מריץ את ה-CLI, ולכן
הטסט מקבע את הפקודה שהבוט שולח, ולא את ההתנהגות של ה-CLI.
"""

from __future__ import annotations

import re
import shlex
import types

import pytest

import main as m
import src.infrastructure.composition.webapp_container as webapp_container

BASE = "https://mcp.example.test"
TOKEN = "ck_test_token"


class _Message:
    def __init__(self):
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class _Facade:
    def __init__(self):
        self.scopes = None

    def issue_mcp_token(self, user_id, *, label, scopes):
        self.scopes = scopes
        return TOKEN


async def _run(monkeypatch, args):
    monkeypatch.setenv("MCP_SERVER_URL", BASE)
    facade = _Facade()
    monkeypatch.setattr(webapp_container, "get_files_facade", lambda: facade)
    message = _Message()
    update = types.SimpleNamespace(
        message=message,
        effective_message=message,
        effective_chat=types.SimpleNamespace(type="private"),
        effective_user=types.SimpleNamespace(id=123),
    )
    context = types.SimpleNamespace(args=args)
    await m.connect_claude_command(update, context)
    assert len(message.replies) == 1, message.replies
    return message.replies[0], facade


def _add_command(reply: str) -> list[str]:
    """הפקודה שהמשתמש מעתיק, מפורקת למילים כמו שה-shell יפרק אותה."""
    found = [c for c in re.findall(r"<code>(.*?)</code>", reply, flags=re.S) if c.startswith("claude mcp add")]
    assert len(found) == 1, reply
    return shlex.split(found[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(("args", "scopes"), [([], ("read",)), (["write"], ("read", "write"))])
async def test_the_add_command_saves_codekeeper_for_all_projects(monkeypatch, args, scopes):
    reply, facade = await _run(monkeypatch, args)
    assert facade.scopes == scopes
    words = _add_command(reply)
    assert words.count("--scope") == 1, words
    assert words[words.index("--scope") + 1] == "user", words
    # שאר הפקודה לא השתנה: אותו שם שרת, אותה כתובת ואותו טוקן.
    without_scope = [w for i, w in enumerate(words) if w != "--scope" and (i == 0 or words[i - 1] != "--scope")]
    assert without_scope == [
        "claude", "mcp", "add", "--transport", "http", "codekeeper", f"{BASE}/mcp",
        "--header", f"Authorization: Bearer {TOKEN}",
    ]
