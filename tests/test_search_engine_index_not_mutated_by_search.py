"""חיפוש טקסט אינו רשאי לשנות את האינדקס שהוא קורא ממנו.

``_text_search`` שלף את קבוצת הקבצים של מילה עם ``word_index.get(word, set())``
— שמחזיר את **הקבוצה השמורה עצמה** כשהמילה קיימת — ואז הרחיב אותה ב-``update``
עם התאמות ה-prefix. מאותו רגע ולכל חיי האינדקס, התאמות חלקיות נספרות כהתאמות
מדויקות ומקבלות ניקוד 2.0 במקום 1.0, כלומר הדירוג נשחק בכל חיפוש נוסף.
"""

import search_engine as se


def _index_with(word_map):
    index = se.SearchIndex()
    for word, keys in word_map.items():
        index.word_index[word].update(keys)
    index.last_update = se.datetime.now(se.timezone.utc)
    return index


def test_text_search_does_not_pollute_the_stored_word_set(monkeypatch):
    monkeypatch.setattr(
        se, "db", type("_DB", (), {"get_latest_version": lambda *_a, **_k: None})(),
        raising=False,
    )
    index = _index_with({"need": {"1:a.py"}, "needle": {"1:b.py"}})
    before = set(index.word_index["need"])

    engine = se.AdvancedSearchEngine()
    engine._text_search("need", index, user_id=1)

    assert index.word_index["need"] == before, (
        "התאמת prefix דלפה לתוך קבוצת ההתאמות המדויקות של המילה"
    )


def test_repeated_searches_keep_scoring_exact_matches_higher(monkeypatch):
    """הניקוד יציב בין חיפושים — מדויק 2.0, חלקי 1.0, גם בפעם השנייה."""
    docs = {
        "1:a.py": {"file_name": "a.py", "code": "need", "programming_language": "python",
                   "tags": [], "created_at": se.datetime.now(se.timezone.utc),
                   "updated_at": se.datetime.now(se.timezone.utc), "version": 1},
        "1:b.py": {"file_name": "b.py", "code": "needle", "programming_language": "python",
                   "tags": [], "created_at": se.datetime.now(se.timezone.utc),
                   "updated_at": se.datetime.now(se.timezone.utc), "version": 1},
    }

    class _DB:
        def get_latest_version(self, user_id, file_name):
            return dict(docs[f"{user_id}:{file_name}"])

    monkeypatch.setattr(se, "db", _DB(), raising=False)
    index = _index_with({"need": {"1:a.py"}, "needle": {"1:b.py"}})
    engine = se.AdvancedSearchEngine()

    first = {r.file_name: r.relevance_score for r in engine._text_search("need", index, 1)}
    second = {r.file_name: r.relevance_score for r in engine._text_search("need", index, 1)}

    assert first == second, "הניקוד השתנה בין שני חיפושים זהים על אותו אינדקס"
