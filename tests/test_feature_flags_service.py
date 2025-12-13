import types


def test_feature_flags_disabled_without_env_key(monkeypatch):
    from services.feature_flags_service import FeatureFlagsService

    monkeypatch.delenv("FLAGSMITH_ENV_KEY", raising=False)
    monkeypatch.delenv("FLAGSMITH_ENVIRONMENT_KEY", raising=False)

    svc = FeatureFlagsService.from_env()
    assert svc.enabled is False
    assert svc.is_enabled("ANY_FLAG") is False
    assert svc.get_value("ANY_VALUE", default="x") == "x"


def test_feature_flags_environment_flag_uses_client():
    from services.feature_flags_service import FeatureFlagsService

    class FakeClient:
        def __init__(self):
            self.calls = []

        def is_feature_enabled(self, name):
            self.calls.append(("is_feature_enabled", name))
            return name == "ON"

    svc = FeatureFlagsService(
        enabled=True,
        fail_open=False,
        identity_cache_ttl_seconds=60,
        client=FakeClient(),
        emit_event=None,
    )
    assert svc.is_enabled("ON") is True
    assert svc.is_enabled("OFF") is False


def test_feature_flags_identity_flags_cached(monkeypatch):
    from services.feature_flags_service import FeatureFlagsService

    class FakeIdentityFlags:
        def __init__(self, enabled: bool):
            self._enabled = enabled
        def is_feature_enabled(self, _name: str) -> bool:
            return self._enabled

    class FakeClient:
        def __init__(self):
            self.calls = 0
        def get_identity_flags(self, identifier=None, traits=None):
            self.calls += 1
            return FakeIdentityFlags(enabled=True)

    svc = FeatureFlagsService(
        enabled=True,
        fail_open=False,
        identity_cache_ttl_seconds=9999,
        client=FakeClient(),
        emit_event=None,
    )

    assert svc.is_enabled("FLAG", user_id="u1") is True
    assert svc.is_enabled("FLAG", user_id="u1") is True
    assert svc._client.calls == 1


def test_feature_flags_fail_open_on_client_error():
    from services.feature_flags_service import FeatureFlagsService

    class FakeClient:
        def is_feature_enabled(self, _name):
            raise RuntimeError("boom")

    svc = FeatureFlagsService(
        enabled=True,
        fail_open=True,
        identity_cache_ttl_seconds=60,
        client=FakeClient(),
        emit_event=None,
    )
    assert svc.is_enabled("FLAG") is True

