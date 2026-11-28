"""יצירת תמונת הקוד בתהליך נפרד (``services/code_image_render.py``): ה-PNG חוזר, כשל חוזר עם ההודעה שלו, ושתי ההמתנות מוגבלות.

הבדיקה הראשונה מריצה את התהליך האמיתי, עם ``CodeImageGenerator`` האמיתי — מה שהבוט מריץ. בלי Playwright זמין הוא נופל ל-PIL,
וגם אז זה PNG.
"""

from __future__ import annotations

import subprocess

import pytest

from services import code_image_render


def _request(code: str) -> dict:
    return code_image_render.build_request(
        code=code, language="python", filename="a.py", style="monokai", theme="dark", font_family="dejavu", width=800, note=None,
    )


@pytest.mark.timeout(120)
def test_the_worker_process_returns_a_png():
    png = code_image_render.render_png(_request("print('hello')\n"))

    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 1000


@pytest.mark.timeout(120)
def test_a_failure_in_the_worker_comes_back_with_its_own_message():
    # ``CodeImageGenerator.generate_image`` זורק ``ValueError("Code cannot be empty")`` על קוד ריק
    with pytest.raises(code_image_render.CodeImageRenderError, match="Code cannot be empty"):
        code_image_render.render_png(_request(""))


def test_a_worker_that_runs_past_the_deadline_is_killed(monkeypatch):
    started = []
    popen = subprocess.Popen

    def _recording_popen(*args, **kwargs):
        proc = popen(*args, **kwargs)
        started.append(proc)
        return proc

    monkeypatch.setattr(code_image_render.subprocess, "Popen", _recording_popen)
    monkeypatch.setattr(code_image_render, "RENDER_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(code_image_render.CodeImageRenderTimeout):
        code_image_render.render_png(_request("print('slow')\n"))

    [proc] = started
    # נהרג ונאסף — לא נשאר תהליך שממשיך לרוץ ברקע
    assert proc.returncode is not None


def test_a_render_that_waits_too_long_for_its_turn_gives_up(monkeypatch):
    monkeypatch.setattr(code_image_render, "SLOT_WAIT_SECONDS", 0.05)
    assert code_image_render._RENDER_SLOTS.acquire(timeout=1)
    try:
        with pytest.raises(code_image_render.CodeImageRenderBusy):
            code_image_render.render_png(_request("print('x')\n"))
    finally:
        # הסמפור ברמת המודול — משוחרר גם כשהבדיקה נכשלת, כדי לא לחסום את הבדיקות שאחריה
        code_image_render._RENDER_SLOTS.release()
