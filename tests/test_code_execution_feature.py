from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_code_execution_service_validation(monkeypatch):
    from services.code_execution_service import CodeExecutionService

    # מונעים ניסיון אמיתי לגעת ב-Docker בזמן init
    monkeypatch.setattr(CodeExecutionService, "_check_docker", lambda self: False)
    monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "false")
    monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "true")

    service = CodeExecutionService()

    ok, err = service.validate_code("")
    assert ok is False
    assert err and "ריק" in err

    ok, err = service.validate_code("import os\nprint('x')")
    assert ok is False
    assert err and "אסור" in err

    ok, err = service.validate_code("import math\nprint(math.pi)")
    assert ok is True
    assert err is None

    ok, err = service.validate_code("import socket\nprint('nope')")
    assert ok is False
    assert err and "אינו מורשה" in err


def test_code_execution_service_fail_closed_defense_in_depth(monkeypatch):
    from services.code_execution_service import CodeExecutionService

    monkeypatch.setattr(CodeExecutionService, "_check_docker", lambda self: False)
    monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "true")
    monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "false")

    service = CodeExecutionService()

    # מדמים "עקיפה" של can_execute כדי לוודא שההגנה הפנימית עדיין fail-closed
    monkeypatch.setattr(service, "can_execute", lambda: (True, None))

    result = service.execute("print('should not run')", timeout=1, memory_limit_mb=64)
    assert result.success is False
    assert result.error_message
    assert "חסומה" in result.error_message or "Docker" in result.error_message


def test_api_code_run_permissions_and_feature_flag(monkeypatch):
    from flask import Flask
    from webapp.code_tools_api import code_tools_bp

    # מונעים init אמיתי של ה-service
    dummy_service = MagicMock()
    dummy_service.get_limits.return_value = {
        "max_timeout_seconds": 30,
        "max_memory_mb": 128,
        "docker_available": False,
        "docker_required": True,
        "fallback_allowed": False,
        "max_code_length_bytes": 51200,
        "max_output_bytes": 102400,
    }
    dummy_service.get_allowed_imports.return_value = ["math"]
    dummy_service.execute.return_value = MagicMock(
        success=True,
        stdout="42\n",
        stderr="",
        exit_code=0,
        execution_time_ms=10,
        truncated=False,
        error_message=None,
    )

    monkeypatch.setenv("FEATURE_CODE_EXECUTION", "true")

    with patch("webapp.code_tools_api.get_code_execution_service", lambda: dummy_service):
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.register_blueprint(code_tools_bp)
        app.testing = True

        with app.test_client() as client:
            # לא מחובר
            resp = client.post("/api/code/run", json={"code": "print(1)"})
            assert resp.status_code == 401

            # מחובר רגיל (לא פרימיום ולא אדמין)
            with client.session_transaction() as sess:
                sess["user_id"] = 111
            resp = client.post("/api/code/run", json={"code": "print(1)"})
            assert resp.status_code == 403
            data = resp.get_json()
            assert data and "Premium" in (data.get("error") or "")

            # פרימיום
            monkeypatch.setenv("PREMIUM_USER_IDS", "222")
            with client.session_transaction() as sess:
                sess["user_id"] = 222
            resp = client.get("/api/code/run/limits")
            assert resp.status_code == 200
            limits = resp.get_json()
            assert limits and limits["enabled"] is True

            resp = client.post("/api/code/run", json={"code": "print(42)"})
            assert resp.status_code == 200
            payload = resp.get_json()
            assert payload and payload["success"] is True
            assert "42" in (payload.get("stdout") or "")

