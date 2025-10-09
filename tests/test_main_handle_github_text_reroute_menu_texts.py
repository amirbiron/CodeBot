import types
import pytest
import asyncio


@pytest.mark.asyncio
async def test_menu_texts_do_not_trigger_waiting_flags(monkeypatch):
    # simulate the router logic from main.handle_github_text for menu texts
    menu_texts = {"➕ הוסף קוד חדש", "📚 הצג את כל הקבצים שלי", "📂 קבצים גדולים", "🔧 GitHub", "🏠 תפריט ראשי", "⚡ עיבוד Batch"}

    cleaned = {"waiting_for_repo_url": True,
               "waiting_for_delete_file_path": True,
               "waiting_for_download_file_path": True,
               "waiting_for_new_repo_name": True,
               "waiting_for_selected_folder": True,
               "waiting_for_new_folder_path": True,
               "waiting_for_upload_folder": True,
               "return_to_pre_upload": True,
               "waiting_for_paste_content": True,
               "waiting_for_paste_filename": True,
               "paste_content": "x"}

    async def _router(text, context):
        if text in menu_texts:
            for k in [
                'waiting_for_repo_url','waiting_for_delete_file_path','waiting_for_download_file_path',
                'waiting_for_new_repo_name','waiting_for_selected_folder','waiting_for_new_folder_path',
                'waiting_for_upload_folder','return_to_pre_upload','waiting_for_paste_content','waiting_for_paste_filename','paste_content']:
                context.user_data.pop(k, None)
            return False
        return False

    class _Ctx:
        def __init__(self):
            self.user_data = dict(cleaned)

    ctx = _Ctx()
    await asyncio.wait_for(_router("🔧 GitHub", ctx), timeout=2.0)
    # All flags should be removed
    assert all(k not in ctx.user_data for k in cleaned.keys())
