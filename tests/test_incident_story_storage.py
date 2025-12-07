import importlib


def test_save_story_generates_id_when_missing(tmp_path, monkeypatch):
    storage_path = tmp_path / "incident_stories.json"
    monkeypatch.setenv("INCIDENT_STORY_FILE", str(storage_path))
    monkeypatch.delenv("INCIDENT_STORY_DB_ENABLED", raising=False)

    storage_module = importlib.import_module("monitoring.incident_story_storage")
    storage = importlib.reload(storage_module)

    payload = {
        "story_id": None,
        "alert_uid": "alert-123",
        "time_window": {
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-01T01:00:00Z",
        },
        "what_we_saw": {"description": "אירוע בדיקה"},
    }

    saved = storage.save_story(payload)

    assert saved["story_id"]
    assert isinstance(saved["story_id"], str)
