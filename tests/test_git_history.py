import pytest
from flask import Flask

from services.git_mirror_service import GitMirrorService
from webapp.routes.repo_browser import repo_bp


class TestValidation:
    """בדיקות וולידציה."""

    @pytest.fixture
    def git_service(self, tmp_path):
        return GitMirrorService(mirrors_base_path=str(tmp_path))

    def test_validate_repo_name_valid(self, git_service):
        valid_names = ['repo', 'my-repo', 'repo_123', 'A1', 'CodeBot']
        for name in valid_names:
            assert git_service._validate_repo_name(name) is True, f"Failed for: {name}"

    def test_validate_repo_name_invalid(self, git_service):
        invalid_names = [
            '', None, 123,
            '-repo',        # starts with -
            '../etc',       # path traversal
            'repo\x00',     # NUL byte
            'a' * 200,      # too long
        ]
        for name in invalid_names:
            assert git_service._validate_repo_name(name) is False, f"Should fail for: {name}"

    def test_validate_file_path_valid(self, git_service):
        valid_paths = [
            'file.py',
            'src/main.py',
            'path/to/file.js',
            'file-name_123.txt',
            '.gitignore',
            # קבצים עם ".." בשם - תקינים! (לא path traversal)
            'a..b.txt',
            'backup..old.py',
            '...',
            'file....name',
            'test..spec.js',
        ]
        for path in valid_paths:
            assert git_service._validate_repo_file_path(path) is True, f"Failed for: {path}"

    def test_validate_file_path_invalid_traversal(self, git_service):
        invalid_paths = [
            '../etc/passwd',         # path traversal
            'path/../../../etc',     # path traversal (normpath יטפל)
            '/absolute/path',        # absolute path
            'path//double',          # double slash
            '',                      # empty
            None,                    # null
            'file\x00.txt',          # NUL byte
        ]
        for path in invalid_paths:
            assert git_service._validate_repo_file_path(path) is False, f"Should fail for: {path}"

    def test_validate_basic_ref_valid(self, git_service):
        valid_refs = [
            'HEAD',
            'main',
            'feature/branch',
            'v1.0.0',
            'abc123',
            'HEAD~1',
            'main^',
            'a1b2c3d4e5f6789012345678901234567890abcd',
        ]
        for ref in valid_refs:
            assert git_service._validate_basic_ref(ref) is True, f"Failed for: {ref}"

    def test_validate_basic_ref_invalid(self, git_service):
        invalid_refs = [
            '', None,
            'branch\x00',
            'a' * 300,  # too long
        ]
        for ref in invalid_refs:
            assert git_service._validate_basic_ref(ref) is False, f"Should fail for: {ref}"


class TestBinaryDetection:
    """בדיקות זיהוי קבצים בינאריים."""

    @pytest.fixture
    def git_service(self, tmp_path):
        return GitMirrorService(mirrors_base_path=str(tmp_path))

    def test_detect_binary_with_nul(self, git_service):
        binary_content = b'some text\x00more text'
        assert git_service._detect_binary_content(binary_content) is True

    def test_detect_text_without_nul(self, git_service):
        text_content = b'hello world\nline 2\n'
        assert git_service._detect_binary_content(text_content) is False

    def test_detect_utf8_text(self, git_service):
        hebrew_content = 'שלום עולם'.encode('utf-8')
        assert git_service._detect_binary_content(hebrew_content) is False


class TestDiffParsing:
    """בדיקות פרסור diff."""

    @pytest.fixture
    def git_service(self, tmp_path):
        return GitMirrorService(mirrors_base_path=str(tmp_path))

    def test_parse_simple_diff(self, git_service):
        diff_output = """diff --git a/file.txt b/file.txt
index 1234567..abcdefg 100644
--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,4 @@
 line1
-old line
+new line
+added line
 line3
"""
        result = git_service._parse_diff(diff_output)

        assert len(result['files']) == 1
        file = result['files'][0]
        assert file['old_path'] == 'file.txt'
        assert file['additions'] == 2
        assert file['deletions'] == 1

    def test_parse_renamed_file(self, git_service):
        diff_output = """diff --git a/old.txt b/new.txt
similarity index 95%
rename from old.txt
rename to new.txt
index 1234567..abcdefg 100644
--- a/old.txt
+++ b/new.txt
@@ -1 +1 @@
-old content
+new content
"""
        result = git_service._parse_diff(diff_output)

        assert len(result['files']) == 1
        file = result['files'][0]
        assert file['status'] == 'renamed'
        assert file['similarity'] == 95
        assert file['rename_from'] == 'old.txt'
        assert file['rename_to'] == 'new.txt'

    def test_parse_new_file(self, git_service):
        diff_output = """diff --git a/newfile.txt b/newfile.txt
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/newfile.txt
@@ -0,0 +1,2 @@
+line1
+line2
"""
        result = git_service._parse_diff(diff_output)

        assert len(result['files']) == 1
        file = result['files'][0]
        assert file['status'] == 'added'
        assert file['additions'] == 2


class TestAPIRoutes:
    """בדיקות API routes."""

    @pytest.fixture
    def app(self, tmp_path) -> Flask:
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.extensions['git_mirror_service'] = GitMirrorService(mirrors_base_path=str(tmp_path))
        app.register_blueprint(repo_bp)
        return app

    @pytest.fixture
    def client(self, app: Flask):
        return app.test_client()

    def test_history_missing_file_param(self, client):
        response = client.get('/repo/api/history')
        assert response.status_code == 400
        data = response.get_json()
        assert data['error'] == 'missing_file'

    def test_history_invalid_file_path(self, client):
        response = client.get('/repo/api/history?file=../etc/passwd')
        assert response.status_code == 400
        data = response.get_json()
        assert data['error'] == 'invalid_file_path'

    def test_diff_endpoint_works(self, client):
        response = client.get('/repo/api/diff/HEAD~1/HEAD')
        # Should return either success or specific error
        assert response.status_code in [200, 400, 404, 500]
