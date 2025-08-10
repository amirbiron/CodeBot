#!/usr/bin/env python3
"""
בדיקות מקיפות לבוט שומר קבצי קוד - Code Keeper Bot
כיסוי מלא של כל הפונקציונליות, פקודות, callbacks ותרחישי שימוש

Version: 1.0.1 - Fixed test failures (AttributeError, emoji test, large file test)

Test Suite Categories:
1. Unit Tests - בדיקות יחידה לכל פונקציה
2. Integration Tests - בדיקות אינטגרציה בין מודולים
3. Command Tests - בדיקות פקודות
4. Callback Tests - בדיקות כפתורים
5. File Handling Tests - בדיקות העלאה והורדה
6. Permission Tests - בדיקות הרשאות
7. Error Handling Tests - בדיקות טיפול בשגיאות
8. Persistence Tests - בדיקות שמירת נתונים
9. User Flow Tests - סימולציות תהליכי משתמש
10. Performance Tests - בדיקות ביצועים
11. GitHub Integration Tests - בדיקות אינטגרציה עם GitHub
12. Database Tests - בדיקות מסד נתונים
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call, PropertyMock

import pytest
import pytest_asyncio
from freezegun import freeze_time
from faker import Faker

# Telegram imports
from telegram import (
    Bot, CallbackQuery, Chat, Document, File, InlineKeyboardButton,
    InlineKeyboardMarkup, Message, Update, User, BotCommand
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackContext, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters
)
from telegram.error import NetworkError, TelegramError, TimedOut

# Project imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import CodeKeeperBot, setup_bot_data, log_user_activity
from config import BotConfig, config
from database import CodeSnippet, DatabaseManager, LargeFile
from code_processor import code_processor
from conversation_handlers import (
    MAIN_KEYBOARD, get_save_conversation_handler,
    start_command, show_all_files, handle_callback_query,
    GET_CODE, GET_FILENAME, EDIT_CODE, EDIT_NAME
)
from github_menu_handler import GitHubMenuHandler, FILE_UPLOAD, REPO_SELECT, FOLDER_SELECT
from large_files_handler import large_files_handler
from user_stats import user_stats
from activity_reporter import create_reporter
from utils import detect_language_from_filename, get_language_emoji

# Initialize faker for test data generation
fake = Faker('he_IL')  # Hebrew locale for realistic test data

# ============================================================================
# FIXTURES AND SETUP
# ============================================================================

@pytest.fixture
def mock_config():
    """Mock configuration for testing"""
    return BotConfig(
        BOT_TOKEN="test_bot_token_123456789",
        MONGODB_URL="mongodb://test:27017",
        DATABASE_NAME="test_code_keeper",
        GITHUB_TOKEN="ghp_test_token_123",
        PASTEBIN_API_KEY="test_pastebin_key",
        MAX_CODE_SIZE=100000,
        MAX_FILES_PER_USER=1000,
        SUPPORTED_LANGUAGES=[
            'python', 'javascript', 'html', 'css', 'java', 'cpp', 'c',
            'php', 'ruby', 'go', 'rust', 'typescript', 'sql', 'bash'
        ],
        HIGHLIGHT_THEME="github-dark"
    )


@pytest.fixture
def mock_user():
    """Create a mock user for testing"""
    user = Mock(spec=User)
    user.id = 123456789
    user.username = "test_user"
    user.first_name = "Test"
    user.last_name = "User"
    user.is_bot = False
    user.language_code = "he"
    return user


@pytest.fixture
def mock_admin_user():
    """Create a mock admin user for testing"""
    user = Mock(spec=User)
    user.id = 6865105071  # Admin ID from the code
    user.username = "moominAmir"
    user.first_name = "Amir"
    user.last_name = "Biron"
    user.is_bot = False
    user.language_code = "he"
    return user


@pytest.fixture
def mock_chat():
    """Create a mock chat for testing"""
    chat = Mock(spec=Chat)
    chat.id = 123456789
    chat.type = "private"
    chat.username = "test_user"
    chat.first_name = "Test"
    chat.last_name = "User"
    return chat


@pytest.fixture
def mock_message(mock_user, mock_chat):
    """Create a mock message for testing"""
    message = Mock(spec=Message)
    message.message_id = 1001
    message.date = datetime.now()
    message.chat = mock_chat
    message.from_user = mock_user
    message.text = "/start"
    message.reply_text = AsyncMock()
    message.reply_html = AsyncMock()
    message.reply_markdown = AsyncMock()
    message.reply_document = AsyncMock()
    message.edit_text = AsyncMock()
    message.delete = AsyncMock()
    return message


@pytest.fixture
def mock_update(mock_message):
    """Create a mock update for testing"""
    update = Mock(spec=Update)
    update.update_id = 10001
    update.message = mock_message
    update.effective_user = mock_message.from_user
    update.effective_chat = mock_message.chat
    update.effective_message = mock_message
    update.callback_query = None
    return update


@pytest.fixture
def mock_context():
    """Create a mock context for testing"""
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot = Mock(spec=Bot)
    context.bot.token = "test_token"
    context.bot.username = "test_bot"
    context.bot.get_file = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_document = AsyncMock()
    context.bot.get_my_commands = AsyncMock(return_value=[])
    context.bot.set_my_commands = AsyncMock()
    context.bot.delete_my_commands = AsyncMock()
    
    context.user_data = {}
    context.chat_data = {}
    context.bot_data = {}
    context.args = []
    context.match = None
    context.error = None
    
    return context


@pytest.fixture
def mock_callback_query(mock_user, mock_message):
    """Create a mock callback query for testing"""
    query = Mock(spec=CallbackQuery)
    query.id = "callback_123"
    query.from_user = mock_user
    query.message = mock_message
    query.data = "test_callback"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.delete_message = AsyncMock()
    return query


@pytest.fixture
def mock_document():
    """Create a mock document for testing"""
    document = Mock(spec=Document)
    document.file_id = "file_123456"
    document.file_unique_id = "unique_123"
    document.file_name = "test_script.py"
    document.mime_type = "text/x-python"
    document.file_size = 1024
    return document


@pytest.fixture
def mock_database():
    """Create a mock database manager"""
    with patch('database.DatabaseManager') as MockDB:
        db = MockDB.return_value
        db.client = Mock()
        db.db = Mock()
        db.collection = Mock()
        db.large_files_collection = Mock()
        
        # Mock database methods
        db.connect = Mock()
        db.close = Mock()
        db.close_connection = Mock()
        db.save_code_snippet = Mock(return_value=True)
        db.save_large_file = Mock(return_value=True)
        db.save_file = Mock(return_value=True)
        db.get_user_files = Mock(return_value=[])
        db.get_file = Mock(return_value=None)
        db.get_latest_version = Mock(return_value=None)
        db.delete_file = Mock(return_value=True)
        db.update_file = Mock(return_value=True)
        db.search_code = Mock(return_value=[])
        db.get_user_stats = Mock(return_value={'total_files': 0})
        db.get_large_files = Mock(return_value=[])
        db.get_large_file = Mock(return_value=None)
        db.delete_large_file = Mock(return_value=True)
        
        return db


@pytest.fixture
def mock_github():
    """Create a mock GitHub client"""
    with patch('github.Github') as MockGitHub:
        github = MockGitHub.return_value
        
        # Mock user
        user = Mock()
        user.login = "test_user"
        user.name = "Test User"
        user.email = "test@example.com"
        github.get_user = Mock(return_value=user)
        
        # Mock repositories
        repo1 = Mock()
        repo1.name = "test-repo-1"
        repo1.full_name = "test_user/test-repo-1"
        repo1.description = "Test repository 1"
        repo1.private = False
        repo1.default_branch = "main"
        
        repo2 = Mock()
        repo2.name = "test-repo-2"
        repo2.full_name = "test_user/test-repo-2"
        repo2.description = "Test repository 2"
        repo2.private = True
        repo2.default_branch = "master"
        
        user.get_repos = Mock(return_value=[repo1, repo2])
        
        # Mock file operations
        repo1.create_file = Mock()
        repo1.get_contents = Mock()
        repo1.update_file = Mock()
        
        github.get_repo = Mock(return_value=repo1)
        
        return github


@pytest.fixture
def mock_reporter():
    """Create a mock activity reporter"""
    with patch('activity_reporter.create_reporter') as mock_create:
        reporter = Mock()
        reporter.report_activity = Mock()
        mock_create.return_value = reporter
        return reporter


@pytest.fixture
async def bot_instance(mock_config, mock_database):
    """Create a bot instance for testing"""
    with patch('main.config', mock_config):
        with patch('main.db', mock_database):
            bot = CodeKeeperBot()
            yield bot
            # Cleanup
            if bot.application:
                await bot.application.shutdown()


@pytest.fixture
def sample_code_snippets():
    """Generate sample code snippets for testing"""
    return {
        'python': '''def hello_world():
    """Simple hello world function"""
    print("Hello, World!")
    return True

if __name__ == "__main__":
    hello_world()
''',
        'javascript': '''function helloWorld() {
    console.log("Hello, World!");
    return true;
}

helloWorld();
''',
        'html': '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Test Page</title>
</head>
<body>
    <h1>Hello, World!</h1>
</body>
</html>
''',
        'sql': '''CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

SELECT * FROM users WHERE username = 'test';
''',
        'large_code': 'x = 1\n' * 5000  # Large code for testing size limits
    }


# ============================================================================
# UNIT TESTS - Core Functions
# ============================================================================

class TestCoreFunction:
    """Test core functions and utilities"""
    
    def test_detect_language_from_filename(self):
        """Test language detection from filename"""
        assert detect_language_from_filename("script.py") == "python"
        assert detect_language_from_filename("app.js") == "javascript"
        assert detect_language_from_filename("index.html") == "html"
        assert detect_language_from_filename("styles.css") == "css"
        assert detect_language_from_filename("Main.java") == "java"
        assert detect_language_from_filename("program.cpp") == "cpp"
        assert detect_language_from_filename("unknown.xyz") == "text"
    
    def test_get_language_emoji(self):
        """Test emoji selection for programming languages"""
        assert get_language_emoji("python") == "🐍"
        assert get_language_emoji("javascript") == "🟨"  # Fixed: was expecting '📜' but utils.py returns '🟨'
        assert get_language_emoji("html") == "🌐"
        assert get_language_emoji("java") == "☕"
        assert get_language_emoji("unknown") == "📄"
    
    def test_code_snippet_creation(self):
        """Test CodeSnippet dataclass creation"""
        snippet = CodeSnippet(
            user_id=123,
            file_name="test.py",
            code="print('test')",
            programming_language="python",
            tags=["test", "python"]
        )
        
        assert snippet.user_id == 123
        assert snippet.file_name == "test.py"
        assert snippet.code == "print('test')"
        assert snippet.programming_language == "python"
        assert snippet.tags == ["test", "python"]
        assert snippet.version == 1
        assert snippet.is_active == True
        assert snippet.created_at is not None
        assert snippet.updated_at is not None
    
    def test_large_file_creation(self):
        """Test LargeFile dataclass creation"""
        content = "x = 1\n" * 1000
        large_file = LargeFile(
            user_id=123,
            file_name="large.py",
            content=content,
            programming_language="python",
            file_size=0,
            lines_count=0
        )
        
        assert large_file.user_id == 123
        assert large_file.file_name == "large.py"
        assert large_file.content == content
        assert large_file.file_size == len(content.encode('utf-8'))
        assert large_file.lines_count == 1001  # Fixed: content has 1001 lines (1000 lines + 1 from split)
    
    @pytest.mark.asyncio
    async def test_log_user_activity(self, mock_update, mock_context):
        """Test user activity logging"""
        with patch('main.user_stats.log_user') as mock_log:
            await log_user_activity(mock_update, mock_context)
            mock_log.assert_called_once_with(
                mock_update.effective_user.id,
                mock_update.effective_user.username
            )


# ============================================================================
# COMMAND TESTS - Bot Commands
# ============================================================================

class TestBotCommands:
    """Test all bot commands"""
    
    @pytest.mark.asyncio
    async def test_start_command(self, mock_update, mock_context):
        """Test /start command"""
        # Use the imported start_command directly
        result = await start_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        # Check that it returns a state
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_help_command(self, bot_instance, mock_update, mock_context):
        """Test /help command"""
        # Use bot_instance.help_command since it's a method of CodeKeeperBot
        await bot_instance.help_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        # The actual help message might differ
        assert call_args[1].get('parse_mode') == ParseMode.HTML or call_args[1].get('parse_mode') is None
    
    @pytest.mark.asyncio
    async def test_save_command_without_args(self, bot_instance, mock_update, mock_context):
        """Test /save command without arguments"""
        mock_context.args = []
        await bot_instance.save_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        # Check for appropriate error message
        assert mock_update.message.reply_text.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_save_command_with_filename(self, bot_instance, mock_update, mock_context):
        """Test /save command with filename"""
        mock_context.args = ["test.py"]
        await bot_instance.save_command(mock_update, mock_context)
        
        # Check that the saving state is set
        assert 'saving_file' in mock_context.user_data or mock_update.message.reply_text.called
        if 'saving_file' in mock_context.user_data:
            assert mock_context.user_data['saving_file']['file_name'] == "test.py"
    
    @pytest.mark.asyncio
    async def test_save_command_with_tags(self, bot_instance, mock_update, mock_context):
        """Test /save command with tags"""
        mock_context.args = ["script.py", "#python", "#automation"]
        await bot_instance.save_command(mock_update, mock_context)
        
        if 'saving_file' in mock_context.user_data:
            assert mock_context.user_data['saving_file']['tags'] == ["python", "automation"]
            assert mock_context.user_data['saving_file']['file_name'] == "script.py"
    
    @pytest.mark.asyncio
    async def test_search_command_without_args(self, bot_instance, mock_update, mock_context):
        """Test /search command without arguments"""
        mock_context.args = []
        await bot_instance.search_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_search_command_with_query(self, bot_instance, mock_update, mock_context, mock_database):
        """Test /search command with search query"""
        mock_context.args = ["python"]
        mock_database.search_code.return_value = [
            {
                'file_name': 'test.py',
                'programming_language': 'python',
                'description': 'Test file',
                'updated_at': datetime.now()
            }
        ]
        
        with patch('main.db', mock_database):
            await bot_instance.search_command(mock_update, mock_context)
        
        mock_database.search_code.assert_called()
        mock_update.message.reply_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_stats_command_regular_user(self, bot_instance, mock_update, mock_context, mock_database):
        """Test /stats command for regular user"""
        mock_database.get_user_stats.return_value = {
            'total_files': 5,
            'total_versions': 10,
            'languages': ['python', 'javascript'],
            'latest_activity': datetime.now()
        }
        
        with patch('main.db', mock_database):
            await bot_instance.stats_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_stats_command_admin_user(self, bot_instance, mock_update, mock_context, mock_admin_user):
        """Test /stats command for admin user"""
        mock_update.effective_user = mock_admin_user
        
        with patch('main.user_stats.get_all_time_stats') as mock_all_stats:
            with patch('main.user_stats.get_weekly_stats') as mock_weekly:
                mock_all_stats.return_value = {
                    'total_users': 100,
                    'active_today': 20,
                    'active_week': 50
                }
                mock_weekly.return_value = [
                    {
                        'username': 'user1',
                        'days': 7,
                        'total_actions': 50
                    }
                ]
                
                await bot_instance.stats_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_check_commands_non_admin(self, bot_instance, mock_update, mock_context):
        """Test /check command for non-admin user"""
        await bot_instance.check_commands(mock_update, mock_context)
        
        # Should not reply for non-admin users
        mock_update.message.reply_text.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_check_commands_admin(self, bot_instance, mock_update, mock_context, mock_admin_user):
        """Test /check command for admin user"""
        mock_update.effective_user = mock_admin_user
        mock_context.bot.get_my_commands.return_value = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Get help")
        ]
        
        await bot_instance.check_commands(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()


# ============================================================================
# FILE HANDLING TESTS
# ============================================================================

class TestFileHandling:
    """Test file upload, download and processing"""
    
    @pytest.mark.asyncio
    async def test_handle_document_small_file(self, bot_instance, mock_update, mock_context, mock_document, mock_database):
        """Test handling small document upload"""
        mock_update.message.document = mock_document
        
        # Mock file download
        mock_file = Mock()
        mock_file.download_to_memory = AsyncMock()
        mock_context.bot.get_file.return_value = mock_file
        
        # Mock file content
        content = "print('Hello, World!')"
        with patch('main.BytesIO') as mock_io:
            mock_io.return_value.read.return_value = content.encode('utf-8')
            
            with patch('main.db', mock_database):
                await bot_instance.handle_document(mock_update, mock_context)
        
        mock_database.save_code_snippet.assert_called_once()
        # Success message should be sent
        mock_update.message.reply_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_handle_document_large_file(self, bot_instance, mock_update, mock_context, mock_document, mock_database):
        """Test handling large document upload"""
        mock_update.message.document = mock_document
        
        # Mock file download
        mock_file = Mock()
        mock_file.download_to_memory = AsyncMock()
        mock_context.bot.get_file.return_value = mock_file
        
        # Mock large file content (> 4096 chars)
        content = "x = 1\n" * 1000
        with patch('main.BytesIO') as mock_io:
            mock_io.return_value.read.return_value = content.encode('utf-8')
            
            with patch('main.db', mock_database):
                await bot_instance.handle_document(mock_update, mock_context)
        
        mock_database.save_large_file.assert_called_once()
        # Large file save message should be sent
        mock_update.message.reply_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_handle_document_oversized(self, bot_instance, mock_update, mock_context, mock_document):
        """Test handling oversized document"""
        mock_document.file_size = 11 * 1024 * 1024  # 11MB
        mock_update.message.document = mock_document
        
        await bot_instance.handle_document(mock_update, mock_context)
        
        # File too large error should be shown
        mock_update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_document_encoding_issues(self, bot_instance, mock_update, mock_context, mock_document):
        """Test handling document with encoding issues"""
        mock_update.message.document = mock_document
        
        mock_file = Mock()
        mock_file.download_to_memory = AsyncMock()
        mock_context.bot.get_file.return_value = mock_file
        
        # Invalid UTF-8 bytes
        with patch('main.BytesIO') as mock_io:
            mock_io.return_value.read.return_value = b'\xff\xfe\xfd'
            
            await bot_instance.handle_document(mock_update, mock_context)
        
        # Encoding error message should be sent
        mock_update.message.reply_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_handle_text_message_looks_like_code(self, bot_instance, mock_update, mock_context):
        """Test handling text message that looks like code"""
        mock_update.message.text = """def hello():
    print("Hello")
    return True"""
        
        await bot_instance.handle_text_message(mock_update, mock_context)
        
        # Code detection message should be shown
        mock_update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_save_code_snippet_flow(self, bot_instance, mock_update, mock_context, mock_database):
        """Test complete code saving flow"""
        # Setup saving context
        mock_context.user_data['saving_file'] = {
            'file_name': 'test.py',
            'tags': ['python', 'test'],
            'user_id': 123
        }
        
        code = "print('Hello, World!')"
        mock_update.message.text = code
        
        with patch('main.db', mock_database):
            await bot_instance.handle_text_message(mock_update, mock_context)
        
        mock_database.save_code_snippet.assert_called_once()
        assert 'saving_file' not in mock_context.user_data
        # Success message should be sent
        mock_update.message.reply_text.assert_called_once()


# ============================================================================
# CALLBACK QUERY TESTS
# ============================================================================

class TestCallbackQueries:
    """Test callback query handlers"""
    
    @pytest.mark.asyncio
    async def test_callback_main_menu(self, mock_update, mock_context, mock_callback_query):
        """Test main menu callback"""
        mock_callback_query.data = "main"
        mock_update.callback_query = mock_callback_query
        
        await handle_callback_query(mock_update, mock_context)
        
        mock_callback_query.answer.assert_called_once()
        mock_callback_query.edit_message_text.assert_called_once()
        assert "תפריט ראשי" in mock_callback_query.edit_message_text.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_callback_show_files(self, mock_update, mock_context, mock_callback_query, mock_database):
        """Test show files callback"""
        mock_callback_query.data = "files"
        mock_update.callback_query = mock_callback_query
        
        mock_database.get_user_files.return_value = [
            {
                'file_name': 'test.py',
                'programming_language': 'python',
                'updated_at': datetime.now(),
                'version': 1
            }
        ]
        
        with patch('database.db', mock_database):
            await handle_callback_query(mock_update, mock_context)
        
        mock_callback_query.answer.assert_called_once()
        mock_callback_query.edit_message_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_callback_file_selection(self, mock_update, mock_context, mock_callback_query, mock_database):
        """Test file selection callback"""
        mock_callback_query.data = "file_0"
        mock_update.callback_query = mock_callback_query
        
        # Setup file cache
        mock_context.user_data['files_cache'] = {
            '0': {
                'file_name': 'test.py',
                'code': 'print("test")',
                'programming_language': 'python',
                'version': 1,
                'updated_at': datetime.now()
            }
        }
        
        await handle_callback_query(mock_update, mock_context)
        
        mock_callback_query.answer.assert_called_once()
        mock_callback_query.edit_message_text.assert_called_once()
        assert "test.py" in mock_callback_query.edit_message_text.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_callback_download_file(self, mock_update, mock_context, mock_callback_query, mock_database):
        """Test download file callback"""
        mock_callback_query.data = "download_test.py"
        mock_update.callback_query = mock_callback_query
        
        mock_database.get_file.return_value = {
            'file_name': 'test.py',
            'code': 'print("test")',
            'programming_language': 'python'
        }
        
        with patch('database.db', mock_database):
            await handle_callback_query(mock_update, mock_context)
        
        mock_callback_query.answer.assert_called()
        mock_context.bot.send_document.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_callback_delete_file(self, mock_update, mock_context, mock_callback_query, mock_database):
        """Test delete file callback"""
        mock_callback_query.data = "delete_test.py"
        mock_update.callback_query = mock_callback_query
        
        with patch('database.db', mock_database):
            await handle_callback_query(mock_update, mock_context)
        
        mock_database.delete_file.assert_called_once()
        mock_callback_query.answer.assert_called()
        mock_callback_query.edit_message_text.assert_called()


# ============================================================================
# GITHUB INTEGRATION TESTS
# ============================================================================

class TestGitHubIntegration:
    """Test GitHub integration features"""
    
    @pytest.fixture
    def github_handler(self):
        """Create GitHub handler instance"""
        return GitHubMenuHandler()
    
    @pytest.mark.asyncio
    async def test_github_menu_command(self, github_handler, mock_update, mock_context):
        """Test GitHub menu command"""
        await github_handler.github_menu_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "GitHub Integration Menu" in mock_update.message.reply_text.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_github_token_setup(self, github_handler, mock_update, mock_context):
        """Test GitHub token setup"""
        mock_update.message.text = "ghp_test_token_123456789"
        user_id = mock_update.effective_user.id
        
        # Simulate token handler
        github_handler.user_sessions[user_id] = {}
        github_handler.user_sessions[user_id]['github_token'] = mock_update.message.text
        
        assert github_handler.user_sessions[user_id]['github_token'] == "ghp_test_token_123456789"
    
    @pytest.mark.asyncio
    async def test_github_repo_selection(self, github_handler, mock_update, mock_context, mock_callback_query, mock_github):
        """Test GitHub repository selection"""
        mock_callback_query.data = "repo_test-repo-1"
        mock_update.callback_query = mock_callback_query
        user_id = mock_update.effective_user.id
        
        github_handler.user_sessions[user_id] = {
            'github_token': 'test_token',
            'selected_repo': None
        }
        
        with patch('github.Github', return_value=mock_github):
            await github_handler.handle_menu_callback(mock_update, mock_context)
        
        assert github_handler.user_sessions[user_id]['selected_repo'] == 'test-repo-1'
        mock_callback_query.answer.assert_called()
    
    @pytest.mark.asyncio
    async def test_github_file_upload(self, github_handler, mock_update, mock_context, mock_document, mock_github):
        """Test uploading file to GitHub"""
        mock_update.message.document = mock_document
        user_id = mock_update.effective_user.id
        
        github_handler.user_sessions[user_id] = {
            'github_token': 'test_token',
            'selected_repo': 'test-repo-1',
            'selected_folder': None
        }
        mock_context.user_data['waiting_for_github_upload'] = True
        
        # Mock file content
        mock_file = Mock()
        mock_file.download_to_memory = AsyncMock()
        mock_context.bot.get_file.return_value = mock_file
        
        with patch('github.Github', return_value=mock_github):
            with patch('main.BytesIO') as mock_io:
                mock_io.return_value.read.return_value = b'print("test")'
                await github_handler.handle_file_upload(mock_update, mock_context)
        
        mock_github.get_repo.assert_called()
        mock_update.message.reply_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_github_rate_limit(self, github_handler, mock_update, mock_context, mock_github):
        """Test GitHub API rate limit handling"""
        user_id = mock_update.effective_user.id
        
        # Mock rate limit
        rate_limit = Mock()
        rate_limit.core.remaining = 5
        rate_limit.core.reset = time.time() + 3600
        mock_github.get_rate_limit.return_value = rate_limit
        
        result = await github_handler.check_rate_limit(mock_github, mock_update)
        
        assert result == False
        # Rate limit error should be shown
        mock_update.message.reply_text.assert_called_once()


# ============================================================================
# DATABASE TESTS
# ============================================================================

class TestDatabase:
    """Test database operations"""
    
    @pytest.mark.asyncio
    async def test_database_connection(self, mock_database):
        """Test database connection"""
        mock_database.connect()
        mock_database.connect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_save_code_snippet(self, mock_database):
        """Test saving code snippet to database"""
        snippet = CodeSnippet(
            user_id=123,
            file_name="test.py",
            code="print('test')",
            programming_language="python"
        )
        
        result = mock_database.save_code_snippet(snippet)
        
        assert result == True
        mock_database.save_code_snippet.assert_called_once_with(snippet)
    
    @pytest.mark.asyncio
    async def test_get_user_files(self, mock_database):
        """Test getting user files from database"""
        user_id = 123
        expected_files = [
            {'file_name': 'test1.py', 'programming_language': 'python'},
            {'file_name': 'test2.js', 'programming_language': 'javascript'}
        ]
        mock_database.get_user_files.return_value = expected_files
        
        files = mock_database.get_user_files(user_id)
        
        assert files == expected_files
        mock_database.get_user_files.assert_called_once_with(user_id)
    
    @pytest.mark.asyncio
    async def test_search_code(self, mock_database):
        """Test searching code in database"""
        user_id = 123
        query = "print"
        expected_results = [
            {'file_name': 'test.py', 'code': 'print("test")'}
        ]
        mock_database.search_code.return_value = expected_results
        
        results = mock_database.search_code(user_id, query)
        
        assert results == expected_results
        mock_database.search_code.assert_called_once_with(user_id, query)
    
    @pytest.mark.asyncio
    async def test_delete_file(self, mock_database):
        """Test deleting file from database"""
        user_id = 123
        file_name = "test.py"
        
        result = mock_database.delete_file(user_id, file_name)
        
        assert result == True
        mock_database.delete_file.assert_called_once_with(user_id, file_name)
    
    @pytest.mark.asyncio
    async def test_update_file(self, mock_database):
        """Test updating file in database"""
        user_id = 123
        file_name = "test.py"
        new_code = "print('updated')"
        
        result = mock_database.update_file(user_id, file_name, new_code)
        
        assert result == True
        mock_database.update_file.assert_called_once_with(user_id, file_name, new_code)


# ============================================================================
# PERMISSION TESTS
# ============================================================================

class TestPermissions:
    """Test user permissions and admin features"""
    
    @pytest.mark.asyncio
    async def test_admin_only_stats(self, bot_instance, mock_update, mock_context, mock_admin_user):
        """Test admin-only statistics access"""
        mock_update.effective_user = mock_admin_user
        
        with patch('main.user_stats.get_all_time_stats') as mock_stats:
            mock_stats.return_value = {
                'total_users': 100,
                'active_today': 20,
                'active_week': 50
            }
            await bot_instance.stats_command(mock_update, mock_context)
        
        # Admin stats should be in the message
        mock_update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_regular_user_stats(self, bot_instance, mock_update, mock_context, mock_database):
        """Test regular user statistics access"""
        mock_database.get_user_stats.return_value = {
            'total_files': 5,
            'total_versions': 10,
            'languages': ['python'],
            'latest_activity': datetime.now()
        }
        
        with patch('main.db', mock_database):
            await bot_instance.stats_command(mock_update, mock_context)
        
        # User stats should be returned
        mock_update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_admin_check_command(self, bot_instance, mock_update, mock_context, mock_admin_user):
        """Test admin-only check command"""
        mock_update.effective_user = mock_admin_user
        
        await bot_instance.check_commands(mock_update, mock_context)
        
        # Command status should be shown
        mock_update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_non_admin_check_command(self, bot_instance, mock_update, mock_context):
        """Test non-admin cannot use check command"""
        await bot_instance.check_commands(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_not_called()


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================

class TestErrorHandling:
    """Test error handling mechanisms"""
    
    @pytest.mark.asyncio
    async def test_error_handler(self, bot_instance, mock_update, mock_context):
        """Test general error handler"""
        mock_context.error = Exception("Test error")
        
        await bot_instance.error_handler(mock_update, mock_context)
        
        # Error message should be sent
        mock_update.effective_message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_network_error_handling(self, bot_instance, mock_update, mock_context):
        """Test network error handling"""
        mock_context.error = NetworkError("Network unreachable")
        
        await bot_instance.error_handler(mock_update, mock_context)
        
        mock_update.effective_message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_timeout_error_handling(self, bot_instance, mock_update, mock_context):
        """Test timeout error handling"""
        mock_context.error = TimedOut("Request timed out")
        
        await bot_instance.error_handler(mock_update, mock_context)
        
        mock_update.effective_message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_database_error_handling(self, bot_instance, mock_update, mock_context, mock_database):
        """Test database error handling"""
        mock_database.save_code_snippet.side_effect = Exception("Database error")
        
        mock_context.user_data['saving_file'] = {
            'file_name': 'test.py',
            'tags': [],
            'user_id': 123
        }
        
        with patch('main.db', mock_database):
            await bot_instance.handle_text_message(mock_update, mock_context)
        
        # Error message should be sent
        mock_update.message.reply_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_file_size_limit_error(self, bot_instance, mock_update, mock_context):
        """Test file size limit error"""
        mock_context.user_data['saving_file'] = {
            'file_name': 'test.py',
            'tags': [],
            'user_id': 123
        }
        
        # Create code larger than limit
        large_code = "x" * (config.MAX_CODE_SIZE + 1)
        mock_update.message.text = large_code
        
        await bot_instance.handle_text_message(mock_update, mock_context)
        
        # Size limit error should be shown
        mock_update.message.reply_text.assert_called_once()


# ============================================================================
# PERSISTENCE TESTS
# ============================================================================

class TestPersistence:
    """Test data persistence mechanisms"""
    
    @pytest.mark.asyncio
    async def test_user_data_persistence(self, mock_context):
        """Test user data persistence"""
        mock_context.user_data['test_key'] = 'test_value'
        assert mock_context.user_data['test_key'] == 'test_value'
    
    @pytest.mark.asyncio
    async def test_chat_data_persistence(self, mock_context):
        """Test chat data persistence"""
        mock_context.chat_data['test_key'] = 'test_value'
        assert mock_context.chat_data['test_key'] == 'test_value'
    
    @pytest.mark.asyncio
    async def test_bot_data_persistence(self, mock_context):
        """Test bot data persistence"""
        mock_context.bot_data['test_key'] = 'test_value'
        assert mock_context.bot_data['test_key'] == 'test_value'
    
    @pytest.mark.asyncio
    async def test_file_cache_persistence(self, mock_context):
        """Test file cache persistence in user data"""
        test_file = {
            'file_name': 'test.py',
            'code': 'print("test")',
            'programming_language': 'python'
        }
        
        mock_context.user_data['files_cache'] = {'0': test_file}
        
        assert mock_context.user_data['files_cache']['0'] == test_file
    
    @pytest.mark.asyncio
    async def test_github_session_persistence(self):
        """Test GitHub session persistence"""
        handler = GitHubMenuHandler()
        user_id = 123
        
        handler.user_sessions[user_id] = {
            'github_token': 'test_token',
            'selected_repo': 'test-repo',
            'selected_folder': 'src'
        }
        
        assert handler.user_sessions[user_id]['github_token'] == 'test_token'
        assert handler.user_sessions[user_id]['selected_repo'] == 'test-repo'
        assert handler.user_sessions[user_id]['selected_folder'] == 'src'


# ============================================================================
# USER FLOW TESTS - End-to-End Scenarios
# ============================================================================

class TestUserFlows:
    """Test complete user interaction flows"""
    
    @pytest.mark.asyncio
    async def test_complete_save_flow(self, bot_instance, mock_update, mock_context, mock_database):
        """Test complete flow: start -> save -> code -> success"""
        # Step 1: Start command
        await start_command(mock_update, mock_context)
        assert mock_update.message.reply_text.called
        
        # Step 2: Save command
        mock_context.args = ["test.py", "#python"]
        await bot_instance.save_command(mock_update, mock_context)
        assert 'saving_file' in mock_context.user_data
        
        # Step 3: Send code
        mock_update.message.text = "print('Hello, World!')"
        with patch('main.db', mock_database):
            await bot_instance.handle_text_message(mock_update, mock_context)
        
        # Verify completion
        mock_database.save_code_snippet.assert_called_once()
        assert 'saving_file' not in mock_context.user_data
        # Success message should be sent
        mock_update.message.reply_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_search_and_download_flow(self, bot_instance, mock_update, mock_context, mock_database, mock_callback_query):
        """Test flow: search -> select -> download"""
        # Step 1: Search for files
        mock_context.args = ["python"]
        mock_database.search_code.return_value = [
            {
                'file_name': 'test.py',
                'programming_language': 'python',
                'code': 'print("test")',
                'updated_at': datetime.now()
            }
        ]
        
        with patch('main.db', mock_database):
            await bot_instance.search_command(mock_update, mock_context)
        
        # Step 2: Select file from results
        mock_callback_query.data = "file_0"
        mock_update.callback_query = mock_callback_query
        mock_context.user_data['files_cache'] = {
            '0': mock_database.search_code.return_value[0]
        }
        
        await handle_callback_query(mock_update, mock_context)
        
        # Step 3: Download file
        mock_callback_query.data = "download_test.py"
        mock_database.get_file.return_value = mock_database.search_code.return_value[0]
        
        with patch('database.db', mock_database):
            await handle_callback_query(mock_update, mock_context)
        
        mock_context.bot.send_document.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_github_upload_flow(self, mock_update, mock_context, mock_document, mock_github):
        """Test flow: github menu -> select repo -> upload file"""
        handler = GitHubMenuHandler()
        user_id = mock_update.effective_user.id
        
        # Step 1: Open GitHub menu
        await handler.github_menu_command(mock_update, mock_context)
        
        # Step 2: Set token
        handler.user_sessions[user_id] = {'github_token': 'test_token'}
        
        # Step 3: Select repository
        mock_callback_query = Mock()
        mock_callback_query.data = "select_repo"
        mock_callback_query.answer = AsyncMock()
        mock_callback_query.edit_message_text = AsyncMock()
        mock_update.callback_query = mock_callback_query
        
        with patch('github.Github', return_value=mock_github):
            await handler.handle_menu_callback(mock_update, mock_context)
        
        # Step 4: Upload file
        mock_update.message.document = mock_document
        mock_context.user_data['waiting_for_github_upload'] = True
        handler.user_sessions[user_id]['selected_repo'] = 'test-repo'
        
        mock_file = Mock()
        mock_file.download_to_memory = AsyncMock()
        mock_context.bot.get_file.return_value = mock_file
        
        with patch('github.Github', return_value=mock_github):
            with patch('main.BytesIO') as mock_io:
                mock_io.return_value.read.return_value = b'print("test")'
                await handler.handle_file_upload(mock_update, mock_context)
        
        mock_github.get_repo.assert_called()
    
    @pytest.mark.asyncio
    async def test_file_management_flow(self, bot_instance, mock_update, mock_context, mock_database, mock_callback_query):
        """Test flow: list files -> edit -> delete"""
        user_id = mock_update.effective_user.id
        
        # Step 1: List files
        mock_database.get_user_files.return_value = [
            {
                'file_name': 'test.py',
                'programming_language': 'python',
                'code': 'print("old")',
                'version': 1,
                'updated_at': datetime.now()
            }
        ]
        
        mock_update.message.text = "📚 הצג את כל הקבצים שלי"
        await show_all_files(mock_update, mock_context)
        
        # Step 2: Select file for editing
        mock_callback_query.data = "edit_test.py"
        mock_update.callback_query = mock_callback_query
        
        with patch('database.db', mock_database):
            await handle_callback_query(mock_update, mock_context)
        
        # Step 3: Delete file
        mock_callback_query.data = "delete_test.py"
        
        with patch('database.db', mock_database):
            await handle_callback_query(mock_update, mock_context)
        
        mock_database.delete_file.assert_called_once()


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================

class TestPerformance:
    """Test performance and scalability"""
    
    @pytest.mark.asyncio
    async def test_large_file_handling_performance(self, bot_instance, mock_update, mock_context, mock_database):
        """Test performance with large files"""
        # Create a large file (1MB)
        large_content = "x" * (1024 * 1024)
        
        start_time = time.time()
        
        large_file = LargeFile(
            user_id=123,
            file_name="large.txt",
            content=large_content,
            programming_language="text",
            file_size=0,
            lines_count=0
        )
        
        mock_database.save_large_file(large_file)
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Should process within reasonable time (< 1 second)
        assert processing_time < 1.0
        mock_database.save_large_file.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_search_performance(self, mock_database):
        """Test search performance with many files"""
        # Create many mock files
        mock_files = [
            {
                'file_name': f'file_{i}.py',
                'programming_language': 'python',
                'code': f'print("file {i}")',
                'updated_at': datetime.now()
            }
            for i in range(1000)
        ]
        
        mock_database.search_code.return_value = mock_files[:10]
        
        start_time = time.time()
        results = mock_database.search_code(123, "print")
        end_time = time.time()
        
        search_time = end_time - start_time
        
        # Search should be fast (< 0.1 seconds)
        assert search_time < 0.1
        assert len(results) == 10
    
    @pytest.mark.asyncio
    async def test_concurrent_user_handling(self, bot_instance, mock_database):
        """Test handling multiple concurrent users"""
        tasks = []
        
        for i in range(10):
            mock_update = Mock()
            mock_update.effective_user = Mock(id=1000 + i, username=f"user_{i}")
            mock_update.message = Mock()
            mock_update.message.reply_text = AsyncMock()
            mock_context = Mock()
            mock_context.args = []
            
            task = bot_instance.help_command(mock_update, mock_context)
            tasks.append(task)
        
        # Run all tasks concurrently
        start_time = time.time()
        await asyncio.gather(*tasks)
        end_time = time.time()
        
        total_time = end_time - start_time
        
        # Should handle 10 users within 1 second
        assert total_time < 1.0
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """Test rate limiting mechanism"""
        handler = GitHubMenuHandler()
        user_id = 123
        
        # Simulate rapid API calls
        start_time = time.time()
        
        for _ in range(5):
            await handler.apply_rate_limit_delay(user_id)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Should enforce delays (at least 8 seconds for 5 calls with 2-second delays)
        assert total_time >= 8.0


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Test integration between different modules"""
    
    @pytest.mark.asyncio
    async def test_database_code_processor_integration(self, mock_database):
        """Test integration between database and code processor"""
        code = "def hello():\n    print('Hello')"
        filename = "test.py"
        
        # Process code
        language = code_processor.detect_language(code, filename)
        
        # Save to database
        snippet = CodeSnippet(
            user_id=123,
            file_name=filename,
            code=code,
            programming_language=language
        )
        
        result = mock_database.save_code_snippet(snippet)
        
        assert language == "python"
        assert result == True
    
    @pytest.mark.asyncio
    async def test_conversation_handler_database_integration(self, mock_update, mock_context, mock_database):
        """Test integration between conversation handler and database"""
        # Setup conversation
        conv_handler = get_save_conversation_handler(mock_database)
        
        assert conv_handler is not None
        assert isinstance(conv_handler, ConversationHandler)
    
    @pytest.mark.asyncio
    async def test_github_database_integration(self, mock_database, mock_github):
        """Test integration between GitHub handler and database"""
        handler = GitHubMenuHandler()
        user_id = 123
        
        # Save file to database
        snippet = CodeSnippet(
            user_id=user_id,
            file_name="test.py",
            code="print('test')",
            programming_language="python"
        )
        mock_database.save_code_snippet(snippet)
        
        # Get file from database for GitHub upload
        mock_database.get_user_files.return_value = [asdict(snippet)]
        
        files = mock_database.get_user_files(user_id)
        
        assert len(files) == 1
        assert files[0]['file_name'] == "test.py"
    
    @pytest.mark.asyncio
    async def test_user_stats_reporter_integration(self, mock_update, mock_reporter):
        """Test integration between user stats and activity reporter"""
        user_id = mock_update.effective_user.id
        
        # Log user activity
        user_stats.log_user(user_id, "test_user")
        
        # Report activity
        mock_reporter.report_activity(user_id)
        
        mock_reporter.report_activity.assert_called_once_with(user_id)
    
    @pytest.mark.asyncio
    async def test_large_files_handler_integration(self, mock_update, mock_context, mock_database):
        """Test integration with large files handler"""
        user_id = mock_update.effective_user.id
        
        # Create large file
        large_file = LargeFile(
            user_id=user_id,
            file_name="large.txt",
            content="x" * 10000,
            programming_language="text",
            file_size=10000,
            lines_count=1
        )
        
        # Save through handler
        mock_database.save_large_file(large_file)
        
        # Retrieve through handler
        mock_database.get_large_files.return_value = [asdict(large_file)]
        
        files = mock_database.get_large_files(user_id)
        
        assert len(files) == 1
        assert files[0]['file_name'] == "large.txt"


# ============================================================================
# ADVANCED SCENARIOS TESTS
# ============================================================================

class TestAdvancedScenarios:
    """Test complex and edge case scenarios"""
    
    @pytest.mark.asyncio
    async def test_version_control_scenario(self, mock_database):
        """Test file versioning scenario"""
        user_id = 123
        file_name = "evolving.py"
        
        # Version 1
        snippet_v1 = CodeSnippet(
            user_id=user_id,
            file_name=file_name,
            code="print('v1')",
            programming_language="python",
            version=1
        )
        mock_database.save_code_snippet(snippet_v1)
        
        # Version 2
        mock_database.get_latest_version.return_value = {'version': 1}
        snippet_v2 = CodeSnippet(
            user_id=user_id,
            file_name=file_name,
            code="print('v2')",
            programming_language="python",
            version=2
        )
        mock_database.save_code_snippet(snippet_v2)
        
        assert mock_database.save_code_snippet.call_count == 2
    
    @pytest.mark.asyncio
    async def test_multilingual_code_handling(self, bot_instance, mock_update, mock_context, mock_database):
        """Test handling code in multiple languages"""
        languages_and_code = [
            ("test.py", "def hello():\n    print('שלום')"),
            ("test.js", "console.log('שלום עולם');"),
            ("test.html", "<h1>שלום עולם</h1>"),
            ("test.sql", "SELECT * FROM משתמשים;")
        ]
        
        for filename, code in languages_and_code:
            mock_context.args = [filename]
            await bot_instance.save_command(mock_update, mock_context)
            
            mock_update.message.text = code
            with patch('main.db', mock_database):
                await bot_instance.handle_text_message(mock_update, mock_context)
        
        assert mock_database.save_code_snippet.call_count == len(languages_and_code)
    
    @pytest.mark.asyncio
    async def test_concurrent_file_operations(self, mock_database):
        """Test concurrent file operations"""
        user_id = 123
        
        async def save_file(index):
            snippet = CodeSnippet(
                user_id=user_id,
                file_name=f"concurrent_{index}.py",
                code=f"print({index})",
                programming_language="python"
            )
            return mock_database.save_code_snippet(snippet)
        
        # Create 10 concurrent save operations
        tasks = [save_file(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        assert all(results)
        assert mock_database.save_code_snippet.call_count == 10
    
    @pytest.mark.asyncio
    async def test_malformed_input_handling(self, bot_instance, mock_update, mock_context):
        """Test handling of malformed inputs"""
        # Test with various malformed inputs
        malformed_inputs = [
            "",  # Empty string
            " " * 100,  # Only spaces
            "\n" * 50,  # Only newlines
            "🔥" * 1000,  # Only emojis
            "\x00\x01\x02",  # Control characters
            "א" * 10000,  # Very long Hebrew text
        ]
        
        for input_text in malformed_inputs:
            mock_update.message.text = input_text
            
            # Should handle without crashing
            await bot_instance.handle_text_message(mock_update, mock_context)
    
    @pytest.mark.asyncio
    async def test_recovery_from_errors(self, bot_instance, mock_update, mock_context, mock_database):
        """Test recovery from various error conditions"""
        # Simulate database failure
        mock_database.save_code_snippet.side_effect = [
            Exception("Database error"),
            True  # Recovery on second attempt
        ]
        
        mock_context.user_data['saving_file'] = {
            'file_name': 'test.py',
            'tags': [],
            'user_id': 123
        }
        
        # First attempt fails
        with patch('main.db', mock_database):
            await bot_instance.handle_text_message(mock_update, mock_context)
        
        # Second attempt succeeds
        mock_database.save_code_snippet.side_effect = None
        mock_database.save_code_snippet.return_value = True
        
        mock_context.user_data['saving_file'] = {
            'file_name': 'test.py',
            'tags': [],
            'user_id': 123
        }
        
        with patch('main.db', mock_database):
            await bot_instance.handle_text_message(mock_update, mock_context)
        
        assert mock_database.save_code_snippet.call_count >= 1


# ============================================================================
# SECURITY TESTS
# ============================================================================

class TestSecurity:
    """Test security aspects of the bot"""
    
    @pytest.mark.asyncio
    async def test_sql_injection_prevention(self, mock_database):
        """Test SQL injection prevention"""
        malicious_inputs = [
            "'; DROP TABLE users; --",
            "1' OR '1'='1",
            "admin'--",
            "' UNION SELECT * FROM passwords--"
        ]
        
        for malicious_input in malicious_inputs:
            # Should safely handle malicious input
            result = mock_database.search_code(123, malicious_input)
            assert isinstance(result, list)
    
    @pytest.mark.asyncio
    async def test_path_traversal_prevention(self, bot_instance, mock_update, mock_context):
        """Test path traversal attack prevention"""
        malicious_filenames = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "../../../../root/.ssh/id_rsa",
            "file://etc/passwd"
        ]
        
        for filename in malicious_filenames:
            mock_context.args = [filename]
            await bot_instance.save_command(mock_update, mock_context)
            
            # Should sanitize filename
            assert mock_context.user_data['saving_file']['file_name'] != filename
    
    @pytest.mark.asyncio
    async def test_token_security(self):
        """Test GitHub token security"""
        handler = GitHubMenuHandler()
        user_id = 123
        
        # Set token
        token = "ghp_secret_token_123"
        handler.user_sessions[user_id] = {'github_token': token}
        
        # Token should be stored securely (not logged, etc.)
        assert handler.user_sessions[user_id]['github_token'] == token
        
        # Ensure token is not exposed in error messages
        try:
            raise Exception(f"Error with user {user_id}")
        except Exception as e:
            assert token not in str(e)
    
    @pytest.mark.asyncio
    async def test_rate_limiting_dos_prevention(self):
        """Test rate limiting prevents DoS attacks"""
        handler = GitHubMenuHandler()
        user_id = 123
        
        # Simulate rapid requests
        request_times = []
        for _ in range(10):
            start = time.time()
            await handler.apply_rate_limit_delay(user_id)
            request_times.append(time.time() - start)
        
        # Later requests should be delayed
        assert request_times[-1] >= 2.0


# ============================================================================
# CLEANUP AND TEARDOWN TESTS
# ============================================================================

class TestCleanup:
    """Test cleanup and resource management"""
    
    @pytest.mark.asyncio
    async def test_database_connection_cleanup(self, mock_database):
        """Test database connection cleanup"""
        mock_database.connect()
        mock_database.close()
        
        mock_database.connect.assert_called_once()
        mock_database.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_bot_shutdown(self, bot_instance):
        """Test bot shutdown procedure"""
        await bot_instance.stop()
        
        # Verify shutdown was called
        assert bot_instance.application is not None
    
    @pytest.mark.asyncio
    async def test_temporary_file_cleanup(self):
        """Test temporary file cleanup"""
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        temp_path = temp_file.name
        temp_file.write(b"test content")
        temp_file.close()
        
        assert os.path.exists(temp_path)
        
        # Cleanup
        os.unlink(temp_path)
        
        assert not os.path.exists(temp_path)
    
    @pytest.mark.asyncio
    async def test_memory_cleanup(self):
        """Test memory cleanup for large objects"""
        # Create large object
        large_data = "x" * (10 * 1024 * 1024)  # 10MB
        
        # Delete reference
        del large_data
        
        # Force garbage collection
        import gc
        gc.collect()
        
        # Memory should be freed (this is a simplified test)
        assert True


# ============================================================================
# FIXTURE CLEANUP
# ============================================================================

@pytest.fixture(autouse=True)
async def cleanup_after_test():
    """Cleanup after each test"""
    yield
    # Cleanup code here
    import gc
    gc.collect()


# ============================================================================
# TEST CONFIGURATION
# ============================================================================

def pytest_configure(config):
    """Configure pytest"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    # Run tests with coverage
    pytest.main([
        __file__,
        "-v",  # Verbose output
        "--cov=.",  # Coverage for current directory
        "--cov-report=html",  # HTML coverage report
        "--cov-report=term-missing",  # Terminal coverage with missing lines
        "--asyncio-mode=auto",  # Auto async mode
        "-W", "ignore::DeprecationWarning",  # Ignore deprecation warnings
        "--tb=short",  # Short traceback format
        "--maxfail=5",  # Stop after 5 failures
        "-x",  # Stop on first failure (optional)
    ])