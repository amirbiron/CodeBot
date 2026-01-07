"""Unit/integration tests for CodeExecutionService.

הערה: בדיקות Docker אמיתיות ירוצו רק אם Docker זמין בסביבה.
"""

from __future__ import annotations

import pytest


class TestCodeExecutionService:
    @pytest.fixture
    def service_no_docker(self, monkeypatch):
        from services.code_execution_service import CodeExecutionService

        monkeypatch.setattr(CodeExecutionService, "_check_docker", lambda self: False)
        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "false")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "true")
        return CodeExecutionService()

    @pytest.fixture
    def service_docker_required(self, monkeypatch):
        from services.code_execution_service import CodeExecutionService

        monkeypatch.setattr(CodeExecutionService, "_check_docker", lambda self: False)
        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "true")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "false")
        return CodeExecutionService()

    def test_validate_empty_code(self, service_no_docker):
        ok, err = service_no_docker.validate_code("")
        assert ok is False
        assert err and "ריק" in err

    def test_validate_blocked_keywords(self, service_no_docker):
        cases = [
            "import os\nprint('x')",
            "import subprocess\nprint('x')",
            "__import__('os')",
            "eval('1+1')",
            "exec('print(1)')",
            "open('x.txt','w')",
        ]
        for code in cases:
            ok, err = service_no_docker.validate_code(code)
            assert ok is False
            assert err and "אסור" in err

    def test_validate_ast_allowlist(self, service_no_docker):
        ok, err = service_no_docker.validate_code("import math\nprint(math.pi)")
        assert ok is True
        assert err is None

        ok, err = service_no_docker.validate_code("import socket\nprint('nope')")
        assert ok is False
        assert err and "אינו מורשה" in err

    def test_validate_syntax_error(self, service_no_docker):
        ok, err = service_no_docker.validate_code("def foo( :")
        assert ok is False
        assert err and "Syntax" in err

    def test_fail_closed_without_docker(self, service_docker_required):
        can_exec, err = service_docker_required.can_execute()
        assert can_exec is False
        assert err and "Docker" in err

    def test_fail_closed_defense_in_depth(self, monkeypatch):
        from services.code_execution_service import CodeExecutionService

        monkeypatch.setattr(CodeExecutionService, "_check_docker", lambda self: False)
        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "true")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "false")
        svc = CodeExecutionService()

        # מדמים עקיפה של can_execute()
        monkeypatch.setattr(svc, "can_execute", lambda: (True, None))

        res = svc.execute("print('should not run')", timeout=1, memory_limit_mb=64)
        assert res.success is False
        assert res.error_message
        assert "חסומה" in res.error_message or "Docker" in res.error_message

    def test_get_limits_and_allowed_imports(self, service_no_docker):
        limits = service_no_docker.get_limits()
        assert "max_timeout_seconds" in limits
        assert "max_memory_mb" in limits
        assert "docker_available" in limits
        assert "docker_required" in limits
        assert "fallback_allowed" in limits

        allowed = service_no_docker.get_allowed_imports()
        assert "math" in allowed
        assert "os" not in allowed


class TestDockerExecution:
    @pytest.fixture
    def docker_service(self, monkeypatch):
        from services.code_execution_service import CodeExecutionService

        monkeypatch.setenv("CODE_EXEC_USE_DOCKER", "true")
        monkeypatch.setenv("CODE_EXEC_ALLOW_FALLBACK", "false")
        svc = CodeExecutionService()
        if not svc.is_docker_available():
            pytest.skip("Docker not available")
        return svc

    def test_docker_simple_execution(self, docker_service):
        res = docker_service.execute("print('Docker works!')", timeout=5, memory_limit_mb=128)
        assert res.success is True
        assert "Docker works!" in (res.stdout or "")
        assert res.used_docker is True

