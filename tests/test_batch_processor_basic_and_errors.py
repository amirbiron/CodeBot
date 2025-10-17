import asyncio
import types
import pytest


def _fresh_bp():
    import sys, importlib
    sys.modules.pop('batch_processor', None)
    return importlib.import_module('batch_processor')


@pytest.mark.asyncio
async def test_analyze_batch_happy_path(monkeypatch):
    bp = _fresh_bp()

    # stub db and code service
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, name):
            return {"code": "print(1)", "programming_language": "python"}
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    svc = __import__('services.code_service', fromlist=['code_service'])
    monkeypatch.setattr(svc, 'analyze_code', lambda c, l: {"ok": True}, raising=True)

    # create job and let background task run
    job_id = await bp.batch_processor.analyze_files_batch(7, ["a.py", "b.py", "c.py"]) 
    # wait for completion
    for _ in range(200):
        job = bp.batch_processor.get_job_status(job_id)
        if job and job.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.01)
    job = bp.batch_processor.get_job_status(job_id)
    assert job is not None and job.status == "completed"
    assert job.total == 3 and job.progress == 3
    # verify results shape
    assert set(job.results.keys()) == {"a.py", "b.py", "c.py"}


@pytest.mark.asyncio
async def test_validate_batch_tool_timeouts_and_missing(monkeypatch):
    bp = _fresh_bp()

    # stub db with a single file
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, name):
            return {"code": "print('x')\n", "programming_language": "python"}
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    # monkeypatch _run_local_cmd inside module to simulate timeouts and missing tools
    import batch_processor as bpm
    def fake_run(args_list, cwd, timeout_sec=20):
        tool = args_list[0]
        if tool in ("flake8", "mypy"):
            return {"returncode": 124, "output": "Timeout"}
        if tool in ("bandit", "black", "pylint", "isort", "radon", "eslint", "tsc", "prettier", "shellcheck", "yamllint", "hadolint", "jq", "semgrep"):
            return {"returncode": 127, "output": "Tool not installed"}
        return {"returncode": 0, "output": "ok"}
    monkeypatch.setattr(bpm, "subprocess", types.SimpleNamespace(run=lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())), raising=True)

    job_id = await bp.batch_processor.validate_files_batch(9, ["x.py"]) 
    for _ in range(200):
        job = bp.batch_processor.get_job_status(job_id)
        if job and job.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.01)
    job = bp.batch_processor.get_job_status(job_id)
    assert job is not None and job.status == "completed"
    # one file processed with advanced_checks present
    assert "x.py" in job.results and isinstance(job.results["x.py"].get("result"), dict)


@pytest.mark.asyncio
async def test_export_batch_handles_missing_files(monkeypatch):
    bp = _fresh_bp()

    # db returns None to simulate missing file
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, name):
            return None
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    job_id = await bp.batch_processor.export_files_batch(3, ["missing.py"]) 
    for _ in range(200):
        job = bp.batch_processor.get_job_status(job_id)
        if job and job.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.01)
    job = bp.batch_processor.get_job_status(job_id)
    assert job is not None and job.status == "completed"
    res = job.results.get("missing.py", {})
    assert res.get("success") is False or (isinstance(res.get("result"), dict) and "error" in res.get("result", {}))


@pytest.mark.asyncio
async def test_cancel_job_marks_failed(monkeypatch):
    bp = _fresh_bp()
    job_id = bp.batch_processor.create_job(1, "analyze", ["a.py"])
    # cancel immediately
    ok = bp.batch_processor.cancel_job(job_id)
    assert ok is True
    job = bp.batch_processor.get_job_status(job_id)
    assert job.status == "failed" and job.error_message == "canceled by user"
