import types


def test_integrations_client_session_uses_timeout_and_connector(monkeypatch):
    import http_async as ha

    captured = {}

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            captured['session_kwargs'] = kwargs
            self.closed = False
            self._request = lambda *a, **k: None

    class _FakeConnector:
        def __init__(self, *args, **kwargs):
            captured['connector_kwargs'] = kwargs

    class _FakeTimeout:
        def __init__(self, *args, **kwargs):
            captured['timeout_kwargs'] = kwargs

    monkeypatch.setattr(ha, '_session', None, raising=False)
    monkeypatch.setattr(ha, '_instrument_session', lambda session: None, raising=False)
    monkeypatch.setattr(
        ha,
        'aiohttp',
        types.SimpleNamespace(
            ClientSession=_FakeSession,
            TCPConnector=_FakeConnector,
            ClientTimeout=_FakeTimeout,
        ),
        raising=False,
    )

    _ = ha.get_session()

    assert 'timeout_kwargs' in captured
    assert 'connector_kwargs' in captured
    assert 'session_kwargs' in captured
