"""Tests for GitMirrorService.get_last_commit_info()"""

import pytest
from unittest.mock import MagicMock

from services.git_mirror_service import GitMirrorService


@pytest.fixture
def mock_service(tmp_path):
    """Create a GitMirrorService with mocked git commands."""
    service = GitMirrorService(base_path=str(tmp_path))
    return service


class TestGetLastCommitInfo:
    """Tests for get_last_commit_info method."""

    def test_returns_none_when_mirror_not_exists(self, mock_service):
        """Should return None if mirror doesn't exist."""
        result = mock_service.get_last_commit_info("nonexistent-repo")
        assert result is None

    def test_parses_commit_info_correctly(self, mock_service, tmp_path):
        """Should correctly parse git log output."""
        # Create fake mirror directory
        repo_path = tmp_path / "test-repo.git"
        repo_path.mkdir()

        # Mock git commands
        log_output = "abc123def456\x00John Doe\x002025-01-17T10:30:00+00:00\x00feat: add new feature"
        show_output = "A\tsrc/new_file.py\nM\tsrc/existing.py\nD\told_file.py"

        def mock_run_git(cmd, cwd=None, timeout=60):
            result = MagicMock()
            result.success = True
            result.return_code = 0

            if "log" in cmd:
                result.stdout = log_output
            elif "show" in cmd:
                result.stdout = show_output
            else:
                result.stdout = ""

            result.stderr = ""
            return result

        mock_service._run_git_command = mock_run_git

        result = mock_service.get_last_commit_info("test-repo")

        assert result is not None
        assert result["sha"] == "abc123def456"
        assert result["sha_short"] == "abc123d"
        assert result["author"] == "John Doe"
        assert result["message"] == "feat: add new feature"
        assert len(result["files"]) == 3

        # Check file statuses
        files_by_path = {f["path"]: f for f in result["files"]}
        assert files_by_path["src/new_file.py"]["status"] == "added"
        assert files_by_path["src/existing.py"]["status"] == "modified"
        assert files_by_path["old_file.py"]["status"] == "deleted"

    def test_parses_pipe_in_author_name_correctly(self, mock_service, tmp_path):
        """Pipe in author name should not break commit parsing."""
        repo_path = tmp_path / "test-repo.git"
        repo_path.mkdir()

        log_output = "abc123def456\x00John | Smith\x002025-01-17T10:30:00+00:00\x00feat: message"
        show_output = "M\tsrc/file.py"

        def mock_run_git(cmd, cwd=None, timeout=60):
            result = MagicMock()
            result.success = True
            result.return_code = 0
            result.stdout = log_output if "log" in cmd else show_output
            result.stderr = ""
            return result

        mock_service._run_git_command = mock_run_git

        result = mock_service.get_last_commit_info("test-repo")
        assert result is not None
        assert result["author"] == "John | Smith"
        assert result["date"] == "2025-01-17T10:30:00+00:00"
        assert result["message"] == "feat: message"

    def test_parses_rename_status_correctly(self, mock_service, tmp_path):
        """Renamed files should use the new path (not old\\tnew)."""
        repo_path = tmp_path / "test-repo.git"
        repo_path.mkdir()

        log_output = "abc123def456\x00John Doe\x002025-01-17T10:30:00+00:00\x00refactor: rename file"
        show_output = "R100\tsrc/old_name.py\tsrc/new_name.py"

        def mock_run_git(cmd, cwd=None, timeout=60):
            result = MagicMock()
            result.success = True
            result.return_code = 0
            result.stdout = log_output if "log" in cmd else show_output
            result.stderr = ""
            return result

        mock_service._run_git_command = mock_run_git

        result = mock_service.get_last_commit_info("test-repo")
        assert result is not None
        assert len(result["files"]) == 1

        file0 = result["files"][0]
        assert file0["status"] == "renamed"
        assert file0["old_path"] == "src/old_name.py"
        assert file0["path"] == "src/new_name.py"
        assert file0["name"] == "new_name.py"

    def test_parses_copy_status_correctly(self, mock_service, tmp_path):
        """Copied files should use the destination path."""
        repo_path = tmp_path / "test-repo.git"
        repo_path.mkdir()

        log_output = "abc123def456\x00John Doe\x002025-01-17T10:30:00+00:00\x00feat: copy file"
        show_output = "C100\tsrc/source.py\tsrc/copied.py"

        def mock_run_git(cmd, cwd=None, timeout=60):
            result = MagicMock()
            result.success = True
            result.return_code = 0
            result.stdout = log_output if "log" in cmd else show_output
            result.stderr = ""
            return result

        mock_service._run_git_command = mock_run_git

        result = mock_service.get_last_commit_info("test-repo")
        assert result is not None
        assert len(result["files"]) == 1
        file0 = result["files"][0]
        assert file0["status"] == "copied"
        assert file0["old_path"] == "src/source.py"
        assert file0["path"] == "src/copied.py"

    def test_truncates_files_over_limit(self, mock_service, tmp_path):
        """Should truncate file list and set truncated flag."""
        repo_path = tmp_path / "test-repo.git"
        repo_path.mkdir()

        log_output = "abc123\x00Author\x002025-01-17T10:30:00+00:00\x00Big commit"
        # Generate 15 files
        files = [f"M\tfile{i}.py" for i in range(15)]
        show_output = "\n".join(files)

        def mock_run_git(cmd, cwd=None, timeout=60):
            result = MagicMock()
            result.success = True
            result.return_code = 0
            result.stdout = log_output if "log" in cmd else show_output
            result.stderr = ""
            return result

        mock_service._run_git_command = mock_run_git

        result = mock_service.get_last_commit_info("test-repo")

        assert result["total_files"] == 15
        assert len(result["files"]) == 10  # max_files limit
        assert result["truncated"] is True

