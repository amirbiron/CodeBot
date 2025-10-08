from refactoring_engine import CodeAnalyzer


def test_analyzer_parses_decorators_returns_and_class_attrs():
    code = (
        "def dec(f):\n    return f\n\n"
        "@dec\n"
        "def func(a: int) -> str:\n    return 'x'\n\n"
        "@dataclass\n"
        "class C(Base):\n    x = 1\n    def m(self):\n        return self.x\n"
    )
    an = CodeAnalyzer(code, "rich.py")
    assert an.analyze() is True
    # פונקציות ודקורטורים
    assert any(f.name == 'func' for f in an.functions)
    f = next(f for f in an.functions if f.name == 'func')
    assert f.returns is not None
    assert f.decorators and len(f.decorators) >= 1
    # מחלקה, base classes ודקורטורים
    assert any(c.name == 'C' for c in an.classes)
    c = next(c for c in an.classes if c.name == 'C')
    assert c.base_classes and any('Base' in b for b in c.base_classes)
    assert c.decorators is not None
    # attributes
    assert 'x' in c.attributes

