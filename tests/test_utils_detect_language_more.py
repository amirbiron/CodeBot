from utils import detect_language_from_filename


def test_detect_language_from_filename_more_cases():
    # Makefile ללא סיומת
    assert detect_language_from_filename("Makefile") == "makefile"

    # dotenv / env
    assert detect_language_from_filename(".env") == "env"

    # Markdown סיומות נוספות ורישיות
    assert detect_language_from_filename("README.MD") == "markdown"
    assert detect_language_from_filename("README.markdown") == "markdown"

    # YAML
    assert detect_language_from_filename("docker-compose.yml") == "yaml"
    assert detect_language_from_filename("config.yaml") == "yaml"

    # לא ידוע
    assert detect_language_from_filename("unknown.weird") == "text"
