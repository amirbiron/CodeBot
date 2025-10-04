# 🧪 שיפור כיסוי טסטים

## 📊 מצב נוכחי

```
קוד ייצור: 49,080 שורות
טסטים:     4,405 שורות  
כיסוי:     ~9% 😟
```

### קבצים קריטיים ללא כיסוי מספק:
1. `bot_handlers.py` (1,236 שורות) - ⚠️ לב הבוט!
2. `main.py` (2,322 שורות) - ⚠️ אתחול קריטי
3. `github_menu_handler.py` - 🟡 כיסוי חלקי
4. `file_manager.py` - 🟡 כיסוי חלקי

---

## 🎯 יעדים

### שלב 1 (חודש 1): **40% כיסוי**
- Critical paths: save, list, show, delete
- Error handling הכי נפוץ
- Database operations

### שלב 2 (חודש 2): **60% כיסוי**
- GitHub integration flows
- Drive integration flows
- Advanced search
- Batch operations

### שלב 3 (חודש 3): **80% כיסוי** 🎉
- Edge cases
- Concurrent operations
- Error recovery
- Performance tests

---

## 📝 טסטים חסרים קריטיים

### 1. Bot Handlers - Critical Flows

```python
# tests/handlers/test_bot_handlers_critical.py

import pytest
from unittest.mock import AsyncMock, MagicMock

class TestShowCommand:
    """טסטים לפקודת /show - הכי פופולרית בבוט"""
    
    @pytest.mark.asyncio
    async def test_show_existing_file(self, mock_update, mock_context):
        """בדיקה: הצגת קובץ קיים מחזירה תוצאה נכונה"""
        # Given
        handler = AdvancedBotHandlers(mock_application)
        mock_context.args = ["test.py"]
        mock_db.get_latest_version.return_value = {
            '_id': '123',
            'file_name': 'test.py',
            'code': 'print("hello")',
            'programming_language': 'python'
        }
        
        # When
        await handler.show_command(mock_update, mock_context)
        
        # Then
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert 'test.py' in call_args[0][0]
        assert 'print("hello")' in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_show_nonexistent_file(self, mock_update, mock_context):
        """בדיקה: קובץ לא קיים מחזיר הודעת שגיאה"""
        handler = AdvancedBotHandlers(mock_application)
        mock_context.args = ["missing.py"]
        mock_db.get_latest_version.return_value = None
        
        await handler.show_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "לא נמצא" in mock_update.message.reply_text.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_show_without_args(self, mock_update, mock_context):
        """בדיקה: /show ללא פרמטרים מחזיר הוראות שימוש"""
        handler = AdvancedBotHandlers(mock_application)
        mock_context.args = []
        
        await handler.show_command(mock_update, mock_context)
        
        assert "אנא ציין שם קובץ" in mock_update.message.reply_text.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_show_with_special_chars(self, mock_update, mock_context):
        """בדיקה: קובץ עם תווים מיוחדים מטופל נכון"""
        handler = AdvancedBotHandlers(mock_application)
        mock_context.args = ["file with spaces.py"]
        mock_db.get_latest_version.return_value = {
            '_id': '123',
            'file_name': 'file with spaces.py',
            'code': 'x = 1',
            'programming_language': 'python'
        }
        
        await handler.show_command(mock_update, mock_context)
        
        # וודא שה-escaping עבד
        assert mock_update.message.reply_text.called


class TestDeleteCommand:
    """טסטים למחיקת קבצים"""
    
    @pytest.mark.asyncio
    async def test_delete_with_confirmation(self):
        """בדיקה: מחיקה עם אישור עובדת"""
        # TODO: implement
        pass
    
    @pytest.mark.asyncio
    async def test_delete_moves_to_recycle(self):
        """בדיקה: מחיקה מעבירה לסל מיחזור"""
        # TODO: implement
        pass
    
    @pytest.mark.asyncio  
    async def test_recycle_bin_ttl(self):
        """בדיקה: קבצים נמחקים מסל המיחזור אחרי TTL"""
        # TODO: implement
        pass


class TestEditCommand:
    """טסטים לעריכת קבצים"""
    
    @pytest.mark.asyncio
    async def test_edit_preserves_metadata(self):
        """בדיקה: עריכה שומרת tags ותיאור"""
        # TODO: implement
        pass
    
    @pytest.mark.asyncio
    async def test_edit_creates_new_version(self):
        """בדיקה: עריכה יוצרת גרסה חדשה"""
        # TODO: implement
        pass
```

---

### 2. Integration Tests - End to End

```python
# tests/integration/test_save_flow_e2e.py

@pytest.mark.integration
class TestSaveFlowE2E:
    """טסטים אינטגרציה לזרימת שמירה מלאה"""
    
    @pytest.mark.asyncio
    async def test_full_save_flow(self, bot_application, mongo_db):
        """
        בדיקת זרימה מלאה:
        1. משתמש שולח /save
        2. מקבל הנחיות
        3. שולח קוד
        4. קוד נשמר במסד
        5. משתמש מקבל אישור
        """
        # Given
        user_id = 12345
        file_name = "test.py"
        code = 'print("hello")'
        
        # When - Step 1: /save command
        update_save = create_mock_update(user_id, f"/save {file_name}")
        await bot_application.process_update(update_save)
        
        # Then - verify response asks for code
        # ...
        
        # When - Step 2: send code
        update_code = create_mock_update(user_id, code)
        await bot_application.process_update(update_code)
        
        # Then - verify saved
        saved = mongo_db.collection.find_one({
            "user_id": user_id,
            "file_name": file_name
        })
        assert saved is not None
        assert saved['code'] == code
        assert saved['programming_language'] == 'python'
    
    @pytest.mark.asyncio
    async def test_search_after_save(self):
        """שמירה ואז חיפוש מיידי מחזיר תוצאה"""
        # TODO: implement
        pass
    
    @pytest.mark.asyncio
    async def test_concurrent_saves_same_user(self):
        """שתי שמירות במקביל מאותו משתמש"""
        # TODO: implement - edge case חשוב!
        pass
```

---

### 3. Error Handling Tests

```python
# tests/test_error_handling.py

class TestErrorRecovery:
    """טסטים להתאוששות משגיאות"""
    
    @pytest.mark.asyncio
    async def test_mongodb_connection_lost(self):
        """בדיקה: MongoDB מתנתק באמצע פעולה"""
        # Simulate connection loss
        # Verify graceful degradation
        # Verify reconnection works
        pass
    
    @pytest.mark.asyncio
    async def test_telegram_api_timeout(self):
        """בדיקה: Telegram API לא עונה"""
        # Simulate timeout
        # Verify retry mechanism
        pass
    
    @pytest.mark.asyncio
    async def test_out_of_memory(self):
        """בדיקה: קובץ ענק גורם ל-OOM"""
        # Try to save huge file
        # Verify proper error message
        # Verify system doesn't crash
        pass
```

---

### 4. Performance Tests

```python
# tests/performance/test_load.py

@pytest.mark.performance
class TestPerformance:
    """בדיקות ביצועים"""
    
    @pytest.mark.asyncio
    async def test_list_1000_files(self):
        """רשימת 1000 קבצים תוך < 1 שניה"""
        # Setup 1000 files
        start = time.time()
        # Call list
        duration = time.time() - start
        assert duration < 1.0
    
    @pytest.mark.asyncio
    async def test_search_large_codebase(self):
        """חיפוש ב-100MB קוד תוך < 2 שניות"""
        # TODO
        pass
    
    def test_memory_usage_stays_under_500mb(self):
        """זיכרון נשאר מתחת ל-500MB גם עם 100 משתמשים פעילים"""
        # TODO
        pass
```

---

## 🛠️ כלים מומלצים

### Coverage Tracking
```bash
# הרצה עם coverage
pytest --cov=. --cov-report=html --cov-report=term

# דוח מפורט
coverage report -m

# HTML report
coverage html
open htmlcov/index.html
```

### Mutation Testing (רמה מתקדמת)
```bash
pip install mutmut
mutmut run
# בודק אם הטסטים מזהים שינויים בקוד
```

### Integration עם CI
```yaml
# .github/workflows/tests.yml
- name: Run tests with coverage
  run: |
    pytest --cov=. --cov-report=xml
    
- name: Upload to Codecov
  uses: codecov/codecov-action@v3
  
- name: Fail if coverage < 80%
  run: |
    coverage report --fail-under=80
```

---

## 📋 תוכנית פעולה

### שבוע 1-2: Foundation
- [ ] Setup coverage tracking ב-CI
- [ ] טסטים ל-`show_command`
- [ ] טסטים ל-`delete_command`
- [ ] טסטים ל-`save_command`
- יעד: 25% כיסוי

### שבוע 3-4: Core Flows
- [ ] טסטים ל-`search_command`
- [ ] טסטים ל-`list_command`
- [ ] טסטים ל-repository layer
- [ ] Integration test לשמירה/קריאה
- יעד: 40% כיסוי

### שבוע 5-8: Advanced
- [ ] טסטים ל-GitHub integration
- [ ] טסטים ל-Drive integration
- [ ] טסטים ל-batch processing
- [ ] Error recovery tests
- יעד: 60% כיסוי

### שבוע 9-12: Excellence
- [ ] Performance tests
- [ ] Concurrency tests
- [ ] Edge cases
- [ ] Load testing
- יעד: 80% כיסוי 🎉

---

## 💡 Best Practices

1. **AAA Pattern**: Arrange, Act, Assert
2. **One assertion per test** (mostly)
3. **Test names = documentation**: `test_what_when_then`
4. **Fixtures for reusable setup**
5. **Parametrize for similar tests**
6. **Mock external dependencies**
7. **Integration tests in separate folder**

---

## 📚 משאבים

- [Pytest Documentation](https://docs.pytest.org/)
- [Testing Python Applications](https://realpython.com/python-testing/)
- [Coverage.py Guide](https://coverage.readthedocs.io/)
- [Effective Python Testing (Talk)](https://www.youtube.com/watch?v=...)

---

**זכור**: טסטים טובים = שינה טובה 😴
