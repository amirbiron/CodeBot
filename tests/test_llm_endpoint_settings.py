"""``services/llm_endpoint_settings.py``: הכללים על ההגדרות של מודל שפה, שהיועץ והחילוץ בחיפוש בתיעוד חולקים.

הכללים עצמם נבדקים דרך שני הצרכנים (``tests/test_advisor_service.py``, ``tests/test_docs_extract_service.py``). כאן
נבדקת ההודעה של כתובת פגומה מול מה שהבדיקה באמת מקבלת: עד 28.11.2026 ההודעות היו מוקלדות, והן הזכירו רק
``https://`` בזמן שגם ``http://`` עבר.
"""

from __future__ import annotations

import pytest

from services.llm_endpoint_settings import BASE_URL_SCHEMES, url_error


@pytest.mark.parametrize("schemes", [BASE_URL_SCHEMES, ("https", "http", "tg"), ("https",)],
                         ids=["base-url", "advisor-contact-url", "one-scheme"])
def test_the_message_names_exactly_the_schemes_that_pass(schemes):
    message = url_error("SOME_URL", "not a url", schemes)

    assert message is not None and message.startswith("SOME_URL ")
    for scheme in schemes:
        assert f"ב-{scheme}://" in message, (scheme, message)
        assert url_error("SOME_URL", f"{scheme}://host.example.test/path", schemes) is None, scheme
    assert message.count("://") == len(schemes), message


@pytest.mark.parametrize("value", ["", "host.example.test/v1", "ftp://host.example.test/", "https://", "https://[::1"])
def test_anything_that_is_not_a_full_url_in_those_schemes_is_an_error_and_not_an_exception(value):
    assert url_error("SOME_URL", value, BASE_URL_SCHEMES) is not None
