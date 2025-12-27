from src.domain.services.language_detector import LanguageDetector


def test_md_with_python_and_top_comment_overrides_to_python() -> None:
    det = LanguageDetector()
    code = "# comment about this script\nimport os\n\ndef main():\n    print('hi')\n"
    assert det.detect_language(code, "block.md") == "python"


def test_md_with_markdown_structures_stays_markdown() -> None:
    det = LanguageDetector()
    md = "# כותרת\n\n- פריט\n- נוסף\n\nקישור: [דוגמה](https://example.com)\n"
    assert det.detect_language(md, "doc.md") == "markdown"

