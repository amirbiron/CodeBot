import types
import pytest

import search_engine as se


class _Perf:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


def _make_docs(n: int):
    docs = []
    for i in range(n):
        docs.append({
            "file_name": f"file_{i}.py",
            "code": f"print('hello {i}')\n",  # תוכן קטן
            "programming_language": "python",
            "tags": ["repo:test" if i % 2 == 0 else "misc"],
            "created_at": se.datetime.now(se.timezone.utc),
            "updated_at": se.datetime.now(se.timezone.utc),
            "version": 1,
        })
    return docs


@pytest.mark.parametrize("total_docs,page_size", [
    (0, 200),
    (1, 200),
    (50, 200),
    (503, 200),  # בודק ריבוי עמודים: 200+200+103
])
def test_rebuild_index_paginates_over_all_files(monkeypatch, total_docs, page_size):
    docs = _make_docs(total_docs)

    class _DB:
        def get_user_files(self, user_id, limit=50, skip=0, projection=None):
            # התנהגות כמו עימוד אמיתי
            return docs[skip: skip + limit]

    # עקיפת מנגנון ביצועים ומדדים כדי שלא יפריע לטסט
    monkeypatch.setattr(se, "db", _DB(), raising=False)
    monkeypatch.setattr(se, "track_performance", lambda *a, **k: _Perf(), raising=False)

    engine = se.AdvancedSearchEngine()
    idx = engine.get_index(user_id=1)
    # הכרחה לבנייה מחדש בכל ריצה
    idx.last_update = se.datetime.min.replace(tzinfo=se.timezone.utc)
    idx.rebuild_index(user_id=1)

    # אימות: כל הקבצים בשפה python הופיעו באינדקס השפה
    python_set = idx.language_index.get("python", set())
    assert len(python_set) == total_docs

    # אימות נוסף: אינדקס התגיות קיבל לפחות את שתי התגיות אם יש מסמכים
    if total_docs > 0:
        assert any(tag in idx.tag_index for tag in ("repo:test", "misc"))
