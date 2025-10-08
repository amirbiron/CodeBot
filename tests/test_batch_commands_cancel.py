def test_batch_module_import_ok():
    mod = __import__('batch_commands')
    assert hasattr(mod, 'setup_batch_handlers')

