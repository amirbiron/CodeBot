from refactoring_engine import RefactoringEngine, CodeAnalyzer


def test_convert_function_to_method_adds_self_with_and_without_args():
    code = (
        "def foo():\n    return 1\n\n"
        "def bar(x, y):\n    return x+y\n"
    )
    eng = RefactoringEngine()
    an = CodeAnalyzer(code, "m.py")
    assert an.analyze() is True
    eng.analyzer = an
    foo = next(f for f in an.functions if f.name == 'foo')
    bar = next(f for f in an.functions if f.name == 'bar')
    m1 = eng._convert_function_to_method(foo)
    m2 = eng._convert_function_to_method(bar)
    assert '(self)' in m1.splitlines()[0]
    assert '(self, x, y)' in m2.splitlines()[0]

