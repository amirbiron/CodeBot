import types


def test_repository_tokens_encrypted_paths(monkeypatch):
    from database.repository import Repository
    import secret_manager as sm

    # Stub users collection
    class Users:
        def __init__(self):
            self._doc = {"github_token": "enc:AAA"}
        def update_one(self, *_a, **_k):
            return types.SimpleNamespace(acknowledged=True)
        def find_one(self, *_a, **_k):
            return dict(self._doc)
    class Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = types.SimpleNamespace()
            self.db = types.SimpleNamespace(users=Users())

    repo = Repository(Mgr())

    # encrypt_secret returns encrypted token -> stored path exercised
    monkeypatch.setattr(sm, "encrypt_secret", lambda plaintext: "enc:ZZZ")
    assert repo.save_github_token(1, "raw") is True

    # decrypt_secret returns plaintext from encrypted value
    monkeypatch.setattr(sm, "decrypt_secret", lambda stored: "raw" if stored.startswith("enc:") else stored)
    assert repo.get_github_token(1) == "raw"
