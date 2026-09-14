"""שחזור אינדקס שהופל — ``services/index_maintenance.py``.

שני ה-endpointים של ``maintenance_cleanup`` מפילים אינדקס TTL ואז יוצרים אותו
מחדש. אם היצירה נכשלת, האוסף נשאר **בלי TTL בכלל** — מצב גרוע מזה שלפני
הקריאה, ובלי חריגה שמדווחת עליו.
"""

from __future__ import annotations

from services.index_maintenance import index_creation_options, restore_dropped_index


class _Coll:
    def __init__(self, *, fail: bool = False):
        self.created: list[tuple] = []
        self.fail = fail

    def create_index(self, keys, **kwargs):
        if self.fail:
            raise RuntimeError("disk full")
        self.created.append((list(keys), kwargs))
        return kwargs.get("name")


class TestCreationOptions:
    def test_metadata_that_is_not_an_option_is_dropped(self):
        """``v`` ו-``ns`` הם מטא-דאטה של מונגו, לא אופציות ליצירה.

        העברתם ל-``create_index`` היא שגיאה — כלומר "שחזור" שנכשל תמיד.
        """
        keys, options = index_creation_options(
            {"key": [("ts", 1)], "v": 2, "ns": "db.coll", "expireAfterSeconds": 86400, "unique": False}
        )

        assert keys == [("ts", 1)]
        assert options == {"expireAfterSeconds": 86400, "unique": False}

    def test_partial_and_sparse_survive(self):
        """אופציות שמשנות את זהות האינדקס חייבות לחזור איתו."""
        _, options = index_creation_options(
            {"key": [("a", 1)], "sparse": True, "partialFilterExpression": {"x": {"$gt": 1}}}
        )

        assert options == {"sparse": True, "partialFilterExpression": {"x": {"$gt": 1}}}


class TestRestore:
    def test_the_old_definition_comes_back_as_it_was(self):
        coll = _Coll()
        meta = {"key": [("ts", 1)], "expireAfterSeconds": 86400, "v": 2}

        assert restore_dropped_index(coll, "metrics_ttl", meta) == "restored"
        assert coll.created == [([("ts", 1)], {"name": "metrics_ttl", "expireAfterSeconds": 86400})]

    def test_nothing_to_restore_is_not_a_failure(self):
        """כשההפלה עצמה לא קרתה (האינדקס לא היה שם) אין מה להחזיר."""
        coll = _Coll()

        assert restore_dropped_index(coll, "metrics_ttl", None) == "not_needed"
        assert restore_dropped_index(coll, "metrics_ttl", {}) == "not_needed"
        assert coll.created == []

    def test_a_failed_restore_says_so_instead_of_pretending(self):
        """הערך שחוזר הוא תיאור של מה שקרה, לא הבטחה שהאינדקס קיים."""
        result = restore_dropped_index(_Coll(fail=True), "metrics_ttl", {"key": [("ts", 1)]})

        assert result.startswith("failed: ")
        assert "disk full" in result
