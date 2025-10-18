import json
import time
import importlib
from datetime import datetime, timezone


def _write_jsonl(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obj in items:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _read_lines(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def test_cleanup_predictions_keeps_recent(tmp_path, monkeypatch):
    c = importlib.import_module("monitoring.cleanup")
    importlib.reload(c)

    now = time.time()
    data_dir = tmp_path / "data"
    preds = data_dir / "predictions_log.json"

    # Direct module to tmp data dir
    monkeypatch.setattr(c, "_DATA_DIR", data_dir)
    monkeypatch.setattr(c, "_PREDICTIONS_FILE", preds)

    # Two old + one recent record
    items = [
        {"ts": datetime.fromtimestamp(now - 300, timezone.utc).isoformat(), "metric": "m", "v": 1},
        {"ts": datetime.fromtimestamp(now - 120, timezone.utc).isoformat(), "metric": "m", "v": 2},
        {"ts": datetime.fromtimestamp(now - 10, timezone.utc).isoformat(), "metric": "m", "v": 3},
    ]
    _write_jsonl(preds, items)

    # Keep only last 60s
    c.cleanup_predictions(max_age_seconds=60, now_ts=now)

    kept = _read_lines(preds)
    assert len(kept) == 1
    obj = json.loads(kept[0])
    assert obj["v"] == 3


def test_cleanup_incidents_keeps_recent(tmp_path, monkeypatch):
    c = importlib.import_module("monitoring.cleanup")
    importlib.reload(c)

    now = time.time()
    data_dir = tmp_path / "data"
    incs = data_dir / "incidents_log.json"

    monkeypatch.setattr(c, "_DATA_DIR", data_dir)
    monkeypatch.setattr(c, "_INCIDENTS_FILE", incs)

    items = [
        {"ts": datetime.fromtimestamp(now - 1000, timezone.utc).isoformat(), "metric": "err", "v": 1},
        {"ts": datetime.fromtimestamp(now - 30, timezone.utc).isoformat(), "metric": "err", "v": 2},
    ]
    _write_jsonl(incs, items)

    c.cleanup_incidents(max_age_seconds=60, now_ts=now)

    kept = _read_lines(incs)
    assert len(kept) == 1
    assert json.loads(kept[0])["v"] == 2


def test_cleanup_skips_outside_data_dir(tmp_path, monkeypatch):
    c = importlib.import_module("monitoring.cleanup")
    importlib.reload(c)

    now = time.time()
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    preds_outside = outside / "predictions_log.json"

    # point base dir to allowed, but file to outside -> should skip
    monkeypatch.setattr(c, "_DATA_DIR", allowed)
    monkeypatch.setattr(c, "_PREDICTIONS_FILE", preds_outside)

    items = [
        {"ts": datetime.fromtimestamp(now - 300, timezone.utc).isoformat(), "metric": "m", "v": 1},
        {"ts": datetime.fromtimestamp(now - 10, timezone.utc).isoformat(), "metric": "m", "v": 2},
    ]
    _write_jsonl(preds_outside, items)

    # Attempt cleanup — should not change file since it's outside base dir
    before = _read_lines(preds_outside)
    c.cleanup_predictions(max_age_seconds=60, now_ts=now)
    after = _read_lines(preds_outside)
    assert after == before


def test_cli_all_and_no_flags(tmp_path, monkeypatch):
    c = importlib.import_module("monitoring.cleanup")
    importlib.reload(c)

    now = time.time()
    data_dir = tmp_path / "data"
    preds = data_dir / "predictions_log.json"
    incs = data_dir / "incidents_log.json"

    monkeypatch.setattr(c, "_DATA_DIR", data_dir)
    monkeypatch.setattr(c, "_PREDICTIONS_FILE", preds)
    monkeypatch.setattr(c, "_INCIDENTS_FILE", incs)

    _write_jsonl(preds, [
        {"ts": datetime.fromtimestamp(now - 600, timezone.utc).isoformat()},
        {"ts": datetime.fromtimestamp(now - 10, timezone.utc).isoformat()},
    ])
    _write_jsonl(incs, [
        {"ts": datetime.fromtimestamp(now - 3600, timezone.utc).isoformat()},
        {"ts": datetime.fromtimestamp(now - 5, timezone.utc).isoformat()},
    ])

    # no flags -> help/usage and exit code 2
    assert c.main([]) == 2

    # run cleanup via CLI
    rc = c.main(["--all", "--max-age-sec", "60"])
    assert rc == 0

    kept_p = _read_lines(preds)
    kept_i = _read_lines(incs)
    assert len(kept_p) == 1
    assert len(kept_i) == 1
