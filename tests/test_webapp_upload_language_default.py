import pytest

from webapp import app as webapp_app


class _StubCodeSnippets:
    def __init__(self, values):
        self._values = values

    def distinct(self, field, query):
        return list(self._values)


class _StubDB:
    def __init__(self, values):
        self.code_snippets = _StubCodeSnippets(values)


@pytest.mark.parametrize(
    "languages",
    [
        ["python", "text", "Go", "PYTHON", "", None],
        ["TEXT", "csharp"],
    ],
)
def test_upload_language_field_defaults_to_detect_extension(monkeypatch, languages):
    """Ensure the upload form keeps 'detect by extension' as default."""
    stub_db = _StubDB(languages)
    monkeypatch.setattr(webapp_app, "get_db", lambda: stub_db)

    flask_app = webapp_app.app
    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 123
            sess["user_data"] = {"id": 123, "first_name": "Test"}

        resp = client.get("/upload")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Human-friendly default should appear once and stay selected.
        assert "זהה לפי סיומת" in html
        assert 'value="text">text<' not in html

        # Ensure actual languages remain selectable after filtering duplicates/text.
        if any(val for val in languages if val and str(val).strip().lower() == "python"):
            assert 'value="python"' in html
        if any(val for val in languages if val and str(val).strip().lower() == "go"):
            assert 'value="Go"' in html or 'value="go"' in html
