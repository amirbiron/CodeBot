import pytest
from webapp.routes.repo_browser import get_current_repo_name


class TestMultiRepoSupport:

    def test_api_list_repos(self, client):
        """בדיקה שה-API מחזיר רשימת ריפויים"""
        response = client.get('/repo/api/repos')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'repos' in data
        assert isinstance(data['repos'], list)

    def test_tree_with_repo_param(self, client):
        """בדיקה שעץ הקבצים עובד עם פרמטר repo"""
        response = client.get('/repo/api/tree?repo=CodeBot')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)

    def test_tree_invalid_repo(self, client):
        """בדיקה שריפו לא קיים מחזיר רשימה ריקה"""
        response = client.get('/repo/api/tree?repo=NonExistent')
        assert response.status_code == 200
        data = response.get_json()
        assert data == []  # אין קבצים לריפו שלא קיים

    def test_file_with_repo_param(self, client):
        """בדיקה שקריאת קובץ עובדת עם פרמטר repo"""
        response = client.get('/repo/api/file/README.md?repo=CodeBot')
        assert response.status_code in [200, 404]  # תלוי אם הקובץ קיים

    def test_select_repo_unauthenticated(self, client):
        """בדיקה שבחירת ריפו דורשת אותנטיקציה"""
        response = client.post('/repo/api/select-repo',
                               json={'repo_name': 'CodeBot'})
        assert response.status_code == 401
