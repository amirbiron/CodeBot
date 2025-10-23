import types
import pytest

# טסטי API בסיסיים ל-Collections (Flask test_client)

@pytest.fixture(scope="module")
def client(monkeypatch):
    import importlib
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    # הפעלת דגל
    try:
        from config import config as cfg
        if hasattr(cfg, 'FEATURE_MY_COLLECTIONS'):
            setattr(cfg, 'FEATURE_MY_COLLECTIONS', True)
    except Exception:
        pass
    # סשן משתמש
    app.testing = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 321
            sess['user_data'] = types.SimpleNamespace(first_name='Api')
        yield c


def test_api_create_list_get_update_delete(client):
    r = client.post('/api/collections', json={'name': 'API Test', 'mode': 'manual'})
    assert r.status_code == 200
    data = r.get_json(); assert data['ok']
    cid = data['collection']['id']

    r = client.get('/api/collections?limit=10&skip=0')
    assert r.status_code == 200 and r.get_json()['ok']

    r = client.get(f'/api/collections/{cid}')
    assert r.status_code == 200 and r.get_json()['ok']

    r = client.put(f'/api/collections/{cid}', json={'description':'d'})
    assert r.status_code == 200 and r.get_json()['ok']

    r = client.delete(f'/api/collections/{cid}')
    assert r.status_code == 200 and r.get_json()['ok']


def test_api_items_flow_and_reorder(client):
    # create
    r = client.post('/api/collections', json={'name': 'With Items', 'mode': 'manual'})
    cid = r.get_json()['collection']['id']

    # add items
    r = client.post(f'/api/collections/{cid}/items', json={'items': [
        {'source':'regular','file_name':'f1.py'},
        {'source':'regular','file_name':'f2.py'}
    ]})
    assert r.status_code == 200 and r.get_json()['ok']

    # list items
    r = client.get(f'/api/collections/{cid}/items?page=1&per_page=20&include_computed=true')
    assert r.status_code == 200 and r.get_json()['ok']

    # reorder
    r = client.put(f'/api/collections/{cid}/reorder', json={'order': [
        {'source':'regular','file_name':'f2.py'},
        {'source':'regular','file_name':'f1.py'}
    ]})
    assert r.status_code == 200 and r.get_json()['ok']

    # remove one
    r = client.delete(f'/api/collections/{cid}/items', json={'items':[{'source':'regular','file_name':'f2.py'}]})
    assert r.status_code == 200 and r.get_json()['ok']


def test_api_4xx(client):
    assert client.get('/api/collections?limit=bad&skip=0').status_code == 400
    assert client.get('/api/collections/invalid-id').get_json()['ok'] is False
    assert client.post('/api/collections', json={'name':''}).get_json()['ok'] is False
    assert client.post('/api/collections/notid/items', json={'items': []}).status_code == 200
    assert client.put('/api/collections/notid/reorder', json={'order': []}).status_code == 200
