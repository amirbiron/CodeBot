import types

def test_repository_image_prefs_save_and_get(monkeypatch):
    from database.repository import Repository

    # Stub users collection with in-memory state
    class Users:
        def __init__(self):
            self._doc = {"image_prefs": {}}
        def update_one(self, *_a, **_k):
            # emulate merge behavior
            set_payload = (_k.get("$set") or {})
            if "image_prefs" in set_payload:
                self._doc["image_prefs"].update(set_payload["image_prefs"])
            return types.SimpleNamespace(acknowledged=True)
        def find_one(self, *_a, **_k):
            return dict(self._doc)

    class Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = types.SimpleNamespace()
            self.db = types.SimpleNamespace(users=Users())

    repo = Repository(Mgr())

    assert repo.save_image_prefs(1, {"theme": "gruvbox", "width": 1400, "font": "jetbrains"}) is True
    out = repo.get_image_prefs(1)
    assert isinstance(out, dict)
    assert out.get("theme") == "gruvbox"
    assert out.get("width") == 1400
    assert out.get("font") == "jetbrains"
