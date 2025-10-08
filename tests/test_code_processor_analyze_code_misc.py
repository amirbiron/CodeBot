import importlib


def test_analyze_code_python_smells_and_scores():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    code = """
import os
def bad(a):
    eval('1+1')
    exec('print(1)')
    if a:
        os.system('echo hi')
    return a
"""
    res = cp.analyze_code(code, 'python')
    assert isinstance(res, dict)
    assert 'code_smells' in res and any('eval' in s for s in res['code_smells'])

