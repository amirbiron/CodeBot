from refactoring_engine import RefactoringEngine, CodeAnalyzer


def test_build_file_content_and_generate_class_name():
    code = (
        "import os\n\n"
        "def user_login():\n    return True\n\n"
        "def user_logout():\n    return False\n"
    )
    eng = RefactoringEngine()
    an = CodeAnalyzer(code, "auth.py")
    assert an.analyze() is True
    eng.analyzer = an
    # build content
    content = eng._build_file_content(an.functions[:1])
    assert "מודול עבור" in content
    # class name generation
    assert eng._generate_class_name('user_auth') == 'UserAuth'

