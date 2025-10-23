import os


def test_comments_api_defs_exist():
    here = os.path.dirname(__file__)
    app_path = os.path.abspath(os.path.join(here, '..', 'webapp', 'app.py'))
    assert os.path.exists(app_path), app_path
    with open(app_path, 'r', encoding='utf-8') as f:
        content = f.read()
    # smoke: endpoints and helpers exist in source
    assert "@app.route('/api/comments'" in content
    assert 'def api_comments_create' in content
    assert 'def api_comments_list' in content
    assert 'def api_comments_reply' in content
    assert 'def api_comments_update' in content
    assert 'def api_comments_delete' in content
    assert 'def api_comments_message_update' in content
    assert 'def api_comments_message_delete' in content
    assert 'def ensure_comments_indexes' in content
