from refactoring_engine import CodeAnalyzer


def test_function_complexity_counts_if_for_while_except_bool():
    code = (
        "def f(a, b, c):\n"
        "    if a:\n        x = 1\n"
        "    for i in range(2):\n        x += i\n"
        "    while False:\n        break\n"
        "    try:\n        x = x\n        \n"
        "    except Exception:\n        x = 0\n"
        "    if a and b or c:\n        x = 2\n"
        "    return x\n"
    )
    an = CodeAnalyzer(code, "cmp.py")
    assert an.analyze() is True
    fn = next(f for f in an.functions if f.name == 'f')
    # לפחות 5: בסיס + if + for + while + except + בוליאני מורכב
    assert fn.complexity >= 5

