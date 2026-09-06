"""ה-chunker חייב להחזיק תקציב בייטים, לא רק חלון שורות.

הרקע (אישו #3332): ``gemini-embedding-001`` מקבל 2,048 טוקנים ו**חותך בשקט**
כל מה שמעבר — בלי שגיאה, עם וקטור שנראה תקין. החיתוך הישן ספר שורות בלבד,
ולכן 220 שורות היו ~4,300 בייט ב-JSON ו-24,000 בייט במארקדאון עברי צפוף.
בפרודקשן חצי מהצ'אנקים חצו את הסף, והווקטור שלהם תיאר רק את ההתחלה שלהם.

הטסטים כאן הורצו על הקוד שלפני התיקון ונפלו שם.
"""

import pytest

from services.chunking_service import (
    CHUNK_MAX_BYTES,
    CHUNKER_VERSION,
    EMBEDDING_METADATA_MAX_BYTES,
    create_embedding_text,
    is_low_information_chunk,
    split_code_to_chunks,
)


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _assert_invariants(chunks, source: str, budget: int = CHUNK_MAX_BYTES) -> None:
    """שלושת האינווריאנטים שהחיתוך חייב לקיים על כל קלט."""
    assert chunks, "chunker returned nothing for non-empty input"

    oversized = [c for c in chunks if _byte_len(c.content) > budget]
    assert not oversized, (
        f"{len(oversized)} chunks exceed the {budget}-byte budget; "
        f"largest is {max(_byte_len(c.content) for c in oversized)} bytes"
    )

    covered = set()
    for chunk in chunks:
        covered.update(range(chunk.start_line, chunk.end_line + 1))
    expected = set(range(1, len(source.splitlines()) + 1))
    assert not (expected - covered), f"lines dropped: {sorted(expected - covered)[:10]}"

    assert [c.index for c in chunks] == list(range(len(chunks))), "chunk index is not contiguous"


class TestByteBudget:
    def test_single_enormous_line_is_split(self):
        """קובץ SVG/JS ממוזער: שורה אחת של ~80KB.

        חיתוך לפי שורות לא היה מפצל אותה בכלל — היא הייתה צ'אנק אחד,
        והווקטור היה מכיר בערך 10% ממנה.
        """
        source = "M 10 20 L 30 40 " * 5000
        chunks = split_code_to_chunks(source)

        _assert_invariants(chunks, source)
        assert len(chunks) > 1
        # כל החתיכות של שורה אחת נושאות את אותו מספר שורה.
        assert all(c.start_line == 1 and c.end_line == 1 for c in chunks)

    def test_dense_hebrew_markdown_is_split(self):
        """עברית עולה ~2 בייט לתו, ולכן 220 שורות חורגות מזמן מהתקציב."""
        source = "\n".join(["## כותרת ארוכה בעברית עם הרבה מילים " * 3] * 220)
        chunks = split_code_to_chunks(source)

        _assert_invariants(chunks, source)
        assert len(chunks) > 1

    def test_plain_code_stays_within_budget(self):
        source = "\n".join(f"    result_{i} = compute_value({i}, flag=True)" for i in range(900))
        _assert_invariants(split_code_to_chunks(source), source)

    def test_no_tail_is_dropped(self):
        """הכלל הישן השמיט חלון אחרון קטן מ-10 שורות.

        נמדד על הקוד שלפני התיקון: ``chunk_size=20, overlap=5`` על 96 שורות
        השמיט את שורה 96, ועל 37 שורות השמיט את 36-37.
        """
        for total, expected_dropped_before in ((96, [96]), (37, [36, 37])):
            source = "\n".join(f"line {i}" for i in range(1, total + 1))
            chunks = split_code_to_chunks(source, chunk_size=20, overlap=5)

            _assert_invariants(chunks, source)
            assert max(c.end_line for c in chunks) == total, (
                f"lines {expected_dropped_before} are dropped again"
            )

    def test_line_ceiling_does_not_collapse_progress(self):
        """כשתקרת השורות בולמת, החפיפה לא רשאית לבלוע את כל ההתקדמות.

        אם החלון היה מתקדם שורה אחת בכל סיבוב, 2,000 שורות היו מייצרות
        כמעט 2,000 צ'אנקים כמעט זהים.
        """
        source = "\n".join(f"x{i}" for i in range(2000))
        chunks = split_code_to_chunks(source, chunk_size=20)

        _assert_invariants(chunks, source)
        assert len(chunks) < 400, f"overlap collapsed progress: {len(chunks)} chunks for 2000 lines"

    def test_consecutive_chunks_overlap(self):
        source = "\n".join(f"    value_{i} = {i} * 2" for i in range(400))
        chunks = split_code_to_chunks(source)
        assert len(chunks) >= 2
        assert chunks[1].start_line <= chunks[0].end_line

    def test_empty_input(self):
        assert split_code_to_chunks("") == []
        assert split_code_to_chunks("   \n  \n") == []

    def test_chunker_version_is_an_int(self):
        # ``get_snippets_needing_processing`` משווה אותו ב-``$ne``; ערך לא-מספרי
        # היה מחזיר את כל הקורפוס לתור בכל סבב.
        assert isinstance(CHUNKER_VERSION, int) and CHUNKER_VERSION >= 2


class TestLowInformationChunk:
    def test_number_dump_is_flagged(self):
        """קובץ ה-export של טבלת האמבדינגים עצמה — שורות של מספרים עשרוניים."""
        assert is_low_information_chunk("0.0123456789, " * 60) is True

    def test_real_code_is_not_flagged(self):
        source = "\n".join(
            f"    def handler_{i}(self, request, context):\n"
            f"        return self.dispatch(request, context)"
            for i in range(20)
        )
        assert is_low_information_chunk(source) is False

    def test_dense_markdown_table_is_not_flagged(self):
        """הכיול על 3,483 הצ'אנקים בפרודקשן: התוכן ה"מספרי" ביותר שאינו dump
        עצר ב-0.556 — טבלאות מדידה במארקדאון. אסור שהן ייפסלו."""
        source = "\n".join(
            f"| בקשה {i} | {i * 13}ms | {i * 7}ms | {i % 5}.{i % 9}% |"
            for i in range(60)
        )
        assert is_low_information_chunk(source) is False

    def test_indented_python_is_not_flagged(self):
        """קוד עתיר הזחה הוא 35%-45% רווח מטבעו.

        אילו הרווחים נספרו במונה, קוד אמיתי היה נפסל.
        """
        source = "\n".join("                value = compute(index)" for _ in range(60))
        assert is_low_information_chunk(source) is False

    def test_short_text_is_never_flagged(self):
        # יחס על 5 תווים הוא רעש, לא אות.
        assert is_low_information_chunk("x=1+2") is False
        assert is_low_information_chunk("1,2,3") is False


class TestEmbeddingText:
    def test_creates_combined_text(self):
        text = create_embedding_text(
            code_chunk="def hello(): pass",
            title="hello.py",
            description="A greeting function",
            tags=["python", "utils"],
            language="python",
        )
        assert "hello.py" in text
        assert "greeting function" in text
        assert "python" in text
        assert "def hello()" in text

    def test_metadata_is_capped(self):
        """תיאור ארוך היה מוציא את הטקסט מהתקציב שה-chunker חישב בקפידה."""
        text = create_embedding_text(
            code_chunk="x = 1",
            title="t.py",
            description="d" * 20000,
            language="python",
        )
        metadata = text.split("\n\nCode:\n")[0]
        assert len(metadata.encode("utf-8")) <= EMBEDDING_METADATA_MAX_BYTES

    def test_metadata_truncation_keeps_valid_utf8(self):
        text = create_embedding_text(code_chunk="x = 1", description="ש" * 5000)
        text.encode("utf-8").decode("utf-8")  # must not raise

    def test_code_survives_even_without_metadata(self):
        text = create_embedding_text(code_chunk="print(1)")
        assert "print(1)" in text

    def test_metadata_only_is_not_empty(self):
        # ה-worker מדלג על הטמעת מטא-דאטה כשהטקסט ריק. שם קובץ לבדו חייב לייצר טקסט.
        assert create_embedding_text(code_chunk="", title="a.py").strip()


@pytest.mark.parametrize("budget", [300, 1000, 2000, 6000])
def test_budget_is_respected_for_any_configured_value(budget):
    source = "\n".join(f"const value{i} = fetchSomething({i});" for i in range(500))
    _assert_invariants(split_code_to_chunks(source, max_bytes=budget), source, budget=budget)
