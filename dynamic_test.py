#!/usr/bin/env python3
"""
Dynamic Test Generator for Code Keeper Bot
==========================================
מערכת בדיקות דינמית שסורקת את הקוד ויוצרת בדיקות אוטומטית בזמן ריצה

Features:
- סריקה אוטומטית של כל הפונקציות
- יצירת בדיקות דינמיות
- שימוש ב-inspection ו-reflection
- תמיכה בקונפיגורציה חיצונית
- עדכון אוטומטי כשהקוד משתנה
"""

import ast
import asyncio
import inspect
import json
import os
import re
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import pytest_asyncio
from faker import Faker

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# CONFIGURATION LOADER
# ============================================================================

@dataclass
class TestConfig:
    """Configuration for dynamic tests"""
    skip_functions: Set[str] = field(default_factory=set)
    skip_patterns: List[str] = field(default_factory=list)
    special_params: Dict[str, Dict] = field(default_factory=dict)
    test_data: Dict[str, Any] = field(default_factory=dict)
    mock_configs: Dict[str, Dict] = field(default_factory=dict)
    timeout_seconds: int = 10
    max_test_depth: int = 3
    auto_mock: bool = True
    verbose: bool = False


class ConfigLoader:
    """Load and manage test configuration"""
    
    @staticmethod
    def load_config(config_path: str = "test_config.json") -> TestConfig:
        """Load configuration from JSON file"""
        if not os.path.exists(config_path):
            # Return default config if file doesn't exist
            return TestConfig()
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            config = TestConfig()
            config.skip_functions = set(data.get('skip_functions', []))
            config.skip_patterns = data.get('skip_patterns', [])
            config.special_params = data.get('special_params', {})
            config.test_data = data.get('test_data', {})
            config.mock_configs = data.get('mock_configs', {})
            config.timeout_seconds = data.get('timeout_seconds', 10)
            config.max_test_depth = data.get('max_test_depth', 3)
            config.auto_mock = data.get('auto_mock', True)
            config.verbose = data.get('verbose', False)
            
            return config
            
        except Exception as e:
            print(f"Warning: Could not load config: {e}")
            return TestConfig()


# ============================================================================
# CODE ANALYZER
# ============================================================================

class CodeAnalyzer:
    """Analyze Python code to extract functions and classes"""
    
    def __init__(self, config: TestConfig):
        self.config = config
        self.faker = Faker('he_IL')
        self.discovered_functions = {}
        self.discovered_classes = {}
        self.import_map = {}
        
    def analyze_file(self, filepath: str) -> Dict[str, Any]:
        """Analyze a Python file and extract all testable elements"""
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        
        tree = ast.parse(source)
        
        result = {
            'functions': {},
            'classes': {},
            'async_functions': {},
            'methods': {},
            'imports': {}
        }
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if not self._should_skip_function(node.name):
                    result['functions'][node.name] = self._analyze_function(node)
                    
            elif isinstance(node, ast.AsyncFunctionDef):
                if not self._should_skip_function(node.name):
                    result['async_functions'][node.name] = self._analyze_function(node, is_async=True)
                    
            elif isinstance(node, ast.ClassDef):
                if not self._should_skip_class(node.name):
                    result['classes'][node.name] = self._analyze_class(node)
                    
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self._analyze_import(node, result['imports'])
        
        return result
    
    def _analyze_function(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef], is_async: bool = False) -> Dict:
        """Analyze a function node"""
        params = []
        for arg in node.args.args:
            param_info = {
                'name': arg.arg,
                'annotation': ast.unparse(arg.annotation) if arg.annotation else None
            }
            params.append(param_info)
        
        # Extract decorators
        decorators = [ast.unparse(d) for d in node.decorator_list]
        
        # Extract docstring
        docstring = ast.get_docstring(node)
        
        # Check if function has return statement
        has_return = any(isinstance(n, ast.Return) for n in ast.walk(node))
        
        return {
            'name': node.name,
            'params': params,
            'is_async': is_async,
            'decorators': decorators,
            'docstring': docstring,
            'has_return': has_return,
            'line_number': node.lineno,
            'body_size': len(node.body)
        }
    
    def _analyze_class(self, node: ast.ClassDef) -> Dict:
        """Analyze a class node"""
        methods = {}
        async_methods = {}
        
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if not self._should_skip_function(item.name):
                    methods[item.name] = self._analyze_function(item)
                    
            elif isinstance(item, ast.AsyncFunctionDef):
                if not self._should_skip_function(item.name):
                    async_methods[item.name] = self._analyze_function(item, is_async=True)
        
        # Extract base classes
        bases = [ast.unparse(base) for base in node.bases]
        
        return {
            'name': node.name,
            'methods': methods,
            'async_methods': async_methods,
            'bases': bases,
            'decorators': [ast.unparse(d) for d in node.decorator_list],
            'docstring': ast.get_docstring(node),
            'line_number': node.lineno
        }
    
    def _analyze_import(self, node: Union[ast.Import, ast.ImportFrom], imports: Dict):
        """Analyze import statements"""
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for alias in node.names:
                full_name = f"{module}.{alias.name}" if module else alias.name
                imports[alias.asname or alias.name] = full_name
    
    def _should_skip_function(self, name: str) -> bool:
        """Check if function should be skipped"""
        if name in self.config.skip_functions:
            return True
        
        for pattern in self.config.skip_patterns:
            if re.match(pattern, name):
                return True
        
        # Skip private/protected methods by default
        if name.startswith('_') and not name.startswith('__'):
            return True
        
        return False
    
    def _should_skip_class(self, name: str) -> bool:
        """Check if class should be skipped"""
        return name.startswith('_')


# ============================================================================
# MOCK GENERATOR
# ============================================================================

class MockGenerator:
    """Generate appropriate mocks for different types"""
    
    def __init__(self, config: TestConfig):
        self.config = config
        self.faker = Faker('he_IL')
        self.mock_cache = {}
        
    def generate_mock_for_param(self, param_name: str, param_type: Optional[str] = None, 
                                function_name: Optional[str] = None) -> Any:
        """Generate appropriate mock based on parameter name and type"""
        
        # Check special params configuration
        if function_name and function_name in self.config.special_params:
            if param_name in self.config.special_params[function_name]:
                return self._create_from_config(
                    self.config.special_params[function_name][param_name]
                )
        
        # Generate based on parameter name patterns
        if 'update' in param_name.lower():
            return self._create_update_mock()
        elif 'context' in param_name.lower():
            return self._create_context_mock()
        elif 'user' in param_name.lower():
            return self._create_user_mock()
        elif 'message' in param_name.lower():
            return self._create_message_mock()
        elif 'database' in param_name.lower() or 'db' in param_name.lower():
            return self._create_database_mock()
        elif 'config' in param_name.lower():
            return self._create_config_mock()
        elif 'file' in param_name.lower():
            return self._create_file_mock()
        elif 'callback' in param_name.lower():
            return self._create_callback_mock()
        
        # Generate based on type annotation
        if param_type:
            return self._generate_by_type(param_type)
        
        # Default mock
        return Mock()
    
    def _create_update_mock(self) -> Mock:
        """Create Telegram Update mock"""
        update = Mock()
        update.update_id = self.faker.random_int(10000, 99999)
        update.message = self._create_message_mock()
        update.effective_user = self._create_user_mock()
        update.effective_chat = self._create_chat_mock()
        update.effective_message = update.message
        update.callback_query = None
        return update
    
    def _create_context_mock(self) -> Mock:
        """Create Telegram Context mock"""
        context = Mock()
        context.bot = Mock()
        context.bot.token = "test_token_" + self.faker.uuid4()
        context.bot.username = "test_bot"
        context.bot.get_file = AsyncMock()
        context.bot.send_message = AsyncMock()
        context.bot.send_document = AsyncMock()
        context.user_data = {}
        context.chat_data = {}
        context.bot_data = {}
        context.args = []
        context.match = None
        context.error = None
        return context
    
    def _create_user_mock(self) -> Mock:
        """Create User mock"""
        user = Mock()
        user.id = self.faker.random_int(100000, 999999)
        user.username = self.faker.user_name()
        user.first_name = self.faker.first_name()
        user.last_name = self.faker.last_name()
        user.is_bot = False
        user.language_code = "he"
        return user
    
    def _create_message_mock(self) -> Mock:
        """Create Message mock"""
        message = Mock()
        message.message_id = self.faker.random_int(1000, 9999)
        message.date = datetime.now()
        message.chat = self._create_chat_mock()
        message.from_user = self._create_user_mock()
        message.text = self.faker.sentence()
        message.reply_text = AsyncMock()
        message.reply_html = AsyncMock()
        message.reply_document = AsyncMock()
        message.edit_text = AsyncMock()
        message.delete = AsyncMock()
        return message
    
    def _create_chat_mock(self) -> Mock:
        """Create Chat mock"""
        chat = Mock()
        chat.id = self.faker.random_int(100000, 999999)
        chat.type = "private"
        chat.username = self.faker.user_name()
        chat.first_name = self.faker.first_name()
        chat.last_name = self.faker.last_name()
        return chat
    
    def _create_database_mock(self) -> Mock:
        """Create Database mock"""
        db = Mock()
        db.save_code_snippet = Mock(return_value=True)
        db.get_user_files = Mock(return_value=[])
        db.get_file = Mock(return_value=None)
        db.delete_file = Mock(return_value=True)
        db.search_code = Mock(return_value=[])
        db.get_user_stats = Mock(return_value={'total_files': 0})
        return db
    
    def _create_config_mock(self) -> Mock:
        """Create Config mock"""
        config = Mock()
        config.BOT_TOKEN = "test_token"
        config.MONGODB_URL = "mongodb://test"
        config.MAX_CODE_SIZE = 100000
        config.MAX_FILES_PER_USER = 1000
        config.SUPPORTED_LANGUAGES = ['python', 'javascript', 'html']
        return config
    
    def _create_file_mock(self) -> Mock:
        """Create File/Document mock"""
        file = Mock()
        file.file_id = self.faker.uuid4()
        file.file_name = self.faker.file_name(extension='py')
        file.file_size = self.faker.random_int(100, 10000)
        file.mime_type = "text/plain"
        return file
    
    def _create_callback_mock(self) -> Mock:
        """Create CallbackQuery mock"""
        callback = Mock()
        callback.id = self.faker.uuid4()
        callback.from_user = self._create_user_mock()
        callback.message = self._create_message_mock()
        callback.data = "test_callback"
        callback.answer = AsyncMock()
        callback.edit_message_text = AsyncMock()
        return callback
    
    def _generate_by_type(self, type_str: str) -> Any:
        """Generate mock based on type annotation"""
        if 'str' in type_str:
            return self.faker.sentence()
        elif 'int' in type_str:
            return self.faker.random_int()
        elif 'float' in type_str:
            return self.faker.pyfloat()
        elif 'bool' in type_str:
            return self.faker.boolean()
        elif 'list' in type_str or 'List' in type_str:
            return []
        elif 'dict' in type_str or 'Dict' in type_str:
            return {}
        elif 'Optional' in type_str:
            # 50% chance of None
            return None if self.faker.boolean() else Mock()
        else:
            return Mock()
    
    def _create_from_config(self, config_data: Any) -> Any:
        """Create mock from configuration data"""
        if isinstance(config_data, dict):
            if '_type' in config_data:
                mock_type = config_data['_type']
                if mock_type == 'update':
                    return self._create_update_mock()
                elif mock_type == 'context':
                    return self._create_context_mock()
                elif mock_type == 'user':
                    return self._create_user_mock()
                # Add more types as needed
            else:
                # Create mock with specified attributes
                mock = Mock()
                for key, value in config_data.items():
                    setattr(mock, key, value)
                return mock
        else:
            return config_data


# ============================================================================
# DYNAMIC TEST GENERATOR
# ============================================================================

class DynamicTestGenerator:
    """Generate tests dynamically based on code analysis"""
    
    def __init__(self, config: TestConfig):
        self.config = config
        self.analyzer = CodeAnalyzer(config)
        self.mock_generator = MockGenerator(config)
        self.generated_tests = []
        
    def generate_tests_for_file(self, filepath: str) -> List[Callable]:
        """Generate tests for all functions in a file"""
        analysis = self.analyzer.analyze_file(filepath)
        tests = []
        
        # Generate tests for regular functions
        for func_name, func_info in analysis['functions'].items():
            test = self._generate_function_test(func_name, func_info, filepath)
            if test:
                tests.append(test)
        
        # Generate tests for async functions
        for func_name, func_info in analysis['async_functions'].items():
            test = self._generate_async_function_test(func_name, func_info, filepath)
            if test:
                tests.append(test)
        
        # Generate tests for classes
        for class_name, class_info in analysis['classes'].items():
            class_tests = self._generate_class_tests(class_name, class_info, filepath)
            tests.extend(class_tests)
        
        return tests
    
    def _generate_function_test(self, func_name: str, func_info: Dict, filepath: str) -> Optional[Callable]:
        """Generate test for a regular function"""
        
        def test_function():
            # Import the module dynamically
            module_name = Path(filepath).stem
            module = __import__(module_name)
            
            # Get the function
            if hasattr(module, func_name):
                func = getattr(module, func_name)
                
                # Generate mocks for parameters
                params = []
                for param in func_info['params']:
                    if param['name'] != 'self':
                        mock = self.mock_generator.generate_mock_for_param(
                            param['name'], 
                            param['annotation'],
                            func_name
                        )
                        params.append(mock)
                
                # Call the function with mocks
                try:
                    result = func(*params)
                    
                    # Basic assertions
                    if func_info['has_return']:
                        assert result is not None, f"{func_name} should return a value"
                    
                    # Check that mocks were called (if applicable)
                    for param in params:
                        if hasattr(param, 'assert_called') or hasattr(param, 'called'):
                            pass  # Mock was used
                    
                    print(f"✅ Test passed for {func_name}")
                    
                except Exception as e:
                    if self.config.verbose:
                        print(f"❌ Test failed for {func_name}: {e}")
                    raise
        
        # Set test name
        test_function.__name__ = f"test_{func_name}_dynamic"
        return test_function
    
    def _generate_async_function_test(self, func_name: str, func_info: Dict, filepath: str) -> Optional[Callable]:
        """Generate test for an async function"""
        
        async def test_async_function():
            # Import the module dynamically
            module_name = Path(filepath).stem
            module = __import__(module_name)
            
            # Get the function
            if hasattr(module, func_name):
                func = getattr(module, func_name)
                
                # Generate mocks for parameters
                params = []
                for param in func_info['params']:
                    if param['name'] != 'self':
                        mock = self.mock_generator.generate_mock_for_param(
                            param['name'],
                            param['annotation'],
                            func_name
                        )
                        params.append(mock)
                
                # Call the async function with mocks
                try:
                    result = await func(*params)
                    
                    # Basic assertions
                    if func_info['has_return']:
                        assert result is not None, f"{func_name} should return a value"
                    
                    print(f"✅ Async test passed for {func_name}")
                    
                except Exception as e:
                    if self.config.verbose:
                        print(f"❌ Async test failed for {func_name}: {e}")
                    raise
        
        # Wrap in pytest async decorator
        @pytest.mark.asyncio
        async def wrapped_test():
            await test_async_function()
        
        wrapped_test.__name__ = f"test_{func_name}_async_dynamic"
        return wrapped_test
    
    def _generate_class_tests(self, class_name: str, class_info: Dict, filepath: str) -> List[Callable]:
        """Generate tests for a class and its methods"""
        tests = []
        
        # Generate test for class instantiation
        def test_class_init():
            module_name = Path(filepath).stem
            module = __import__(module_name)
            
            if hasattr(module, class_name):
                cls = getattr(module, class_name)
                
                # Try to instantiate with mocked parameters
                try:
                    # Get __init__ parameters if available
                    if '__init__' in class_info['methods']:
                        init_params = class_info['methods']['__init__']['params']
                        params = []
                        for param in init_params:
                            if param['name'] not in ['self', 'cls']:
                                mock = self.mock_generator.generate_mock_for_param(
                                    param['name'],
                                    param['annotation'],
                                    f"{class_name}.__init__"
                                )
                                params.append(mock)
                        instance = cls(*params)
                    else:
                        instance = cls()
                    
                    assert instance is not None, f"{class_name} should be instantiable"
                    print(f"✅ Class instantiation test passed for {class_name}")
                    
                except Exception as e:
                    if self.config.verbose:
                        print(f"❌ Class instantiation test failed for {class_name}: {e}")
                    raise
        
        test_class_init.__name__ = f"test_{class_name}_init_dynamic"
        tests.append(test_class_init)
        
        # Generate tests for methods
        for method_name, method_info in class_info['methods'].items():
            if method_name not in ['__init__', '__str__', '__repr__']:
                test = self._generate_method_test(class_name, method_name, method_info, filepath)
                if test:
                    tests.append(test)
        
        # Generate tests for async methods
        for method_name, method_info in class_info['async_methods'].items():
            test = self._generate_async_method_test(class_name, method_name, method_info, filepath)
            if test:
                tests.append(test)
        
        return tests
    
    def _generate_method_test(self, class_name: str, method_name: str, method_info: Dict, filepath: str) -> Optional[Callable]:
        """Generate test for a class method"""
        
        def test_method():
            module_name = Path(filepath).stem
            module = __import__(module_name)
            
            if hasattr(module, class_name):
                cls = getattr(module, class_name)
                
                # Create instance with mocked init params
                try:
                    instance = Mock(spec=cls)
                    
                    # Get the actual method
                    if hasattr(cls, method_name):
                        method = getattr(cls, method_name)
                        
                        # Generate mocks for method parameters
                        params = []
                        for param in method_info['params']:
                            if param['name'] not in ['self', 'cls']:
                                mock = self.mock_generator.generate_mock_for_param(
                                    param['name'],
                                    param['annotation'],
                                    f"{class_name}.{method_name}"
                                )
                                params.append(mock)
                        
                        # Call the method
                        result = method(instance, *params)
                        
                        if method_info['has_return']:
                            assert result is not None, f"{class_name}.{method_name} should return a value"
                        
                        print(f"✅ Method test passed for {class_name}.{method_name}")
                        
                except Exception as e:
                    if self.config.verbose:
                        print(f"❌ Method test failed for {class_name}.{method_name}: {e}")
                    raise
        
        test_method.__name__ = f"test_{class_name}_{method_name}_dynamic"
        return test_method
    
    def _generate_async_method_test(self, class_name: str, method_name: str, method_info: Dict, filepath: str) -> Optional[Callable]:
        """Generate test for an async class method"""
        
        @pytest.mark.asyncio
        async def test_async_method():
            module_name = Path(filepath).stem
            module = __import__(module_name)
            
            if hasattr(module, class_name):
                cls = getattr(module, class_name)
                
                try:
                    instance = Mock(spec=cls)
                    
                    if hasattr(cls, method_name):
                        method = getattr(cls, method_name)
                        
                        # Generate mocks for method parameters
                        params = []
                        for param in method_info['params']:
                            if param['name'] not in ['self', 'cls']:
                                mock = self.mock_generator.generate_mock_for_param(
                                    param['name'],
                                    param['annotation'],
                                    f"{class_name}.{method_name}"
                                )
                                params.append(mock)
                        
                        # Call the async method
                        result = await method(instance, *params)
                        
                        if method_info['has_return']:
                            assert result is not None, f"{class_name}.{method_name} should return a value"
                        
                        print(f"✅ Async method test passed for {class_name}.{method_name}")
                        
                except Exception as e:
                    if self.config.verbose:
                        print(f"❌ Async method test failed for {class_name}.{method_name}: {e}")
                    raise
        
        test_async_method.__name__ = f"test_{class_name}_{method_name}_async_dynamic"
        return test_async_method


# ============================================================================
# TEST RUNNER
# ============================================================================

class DynamicTestRunner:
    """Run dynamically generated tests"""
    
    def __init__(self, config_path: str = "test_config.json"):
        self.config = ConfigLoader.load_config(config_path)
        self.generator = DynamicTestGenerator(self.config)
        self.results = {
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }
    
    def discover_and_test(self, target_file: str = "main.py") -> Dict[str, Any]:
        """Discover all functions and run tests"""
        print(f"\n🔍 Analyzing {target_file}...")
        
        if not os.path.exists(target_file):
            print(f"❌ File {target_file} not found!")
            return self.results
        
        # Generate tests
        tests = self.generator.generate_tests_for_file(target_file)
        
        print(f"📊 Generated {len(tests)} tests\n")
        print("=" * 60)
        
        # Run tests
        for test in tests:
            test_name = test.__name__
            print(f"\n🧪 Running {test_name}...")
            
            try:
                if asyncio.iscoroutinefunction(test):
                    asyncio.run(test())
                else:
                    test()
                
                self.results['passed'] += 1
                print(f"   ✅ PASSED")
                
            except AssertionError as e:
                self.results['failed'] += 1
                self.results['errors'].append({
                    'test': test_name,
                    'error': str(e),
                    'type': 'assertion'
                })
                print(f"   ❌ FAILED: {e}")
                
            except Exception as e:
                self.results['failed'] += 1
                self.results['errors'].append({
                    'test': test_name,
                    'error': str(e),
                    'type': 'exception'
                })
                print(f"   💥 ERROR: {e}")
        
        # Print summary
        self._print_summary()
        
        return self.results
    
    def _print_summary(self):
        """Print test results summary"""
        print("\n" + "=" * 60)
        print("📈 TEST RESULTS SUMMARY")
        print("=" * 60)
        
        total = self.results['passed'] + self.results['failed'] + self.results['skipped']
        
        print(f"\n✅ Passed:  {self.results['passed']}/{total}")
        print(f"❌ Failed:  {self.results['failed']}/{total}")
        print(f"⏭️  Skipped: {self.results['skipped']}/{total}")
        
        if self.results['passed'] == total:
            print("\n🎉 All tests passed!")
        elif self.results['failed'] > 0:
            print(f"\n⚠️  {self.results['failed']} tests failed")
            
            if self.config.verbose and self.results['errors']:
                print("\n📋 Error Details:")
                for error in self.results['errors'][:5]:  # Show first 5 errors
                    print(f"   - {error['test']}: {error['error'][:100]}...")
        
        # Calculate success rate
        if total > 0:
            success_rate = (self.results['passed'] / total) * 100
            print(f"\n📊 Success Rate: {success_rate:.1f}%")
    
    def save_results(self, output_file: str = "test_results.json"):
        """Save test results to JSON file"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Results saved to {output_file}")


# ============================================================================
# WATCH MODE
# ============================================================================

class FileWatcher:
    """Watch files for changes and re-run tests automatically"""
    
    def __init__(self, runner: DynamicTestRunner):
        self.runner = runner
        self.last_modified = {}
        
    def watch(self, target_file: str = "main.py", interval: int = 5):
        """Watch file for changes and re-run tests"""
        print(f"\n👁️  Watching {target_file} for changes...")
        print("Press Ctrl+C to stop\n")
        
        try:
            while True:
                # Check if file was modified
                if os.path.exists(target_file):
                    current_mtime = os.path.getmtime(target_file)
                    
                    if target_file not in self.last_modified:
                        self.last_modified[target_file] = current_mtime
                        # Run initial test
                        self.runner.discover_and_test(target_file)
                    
                    elif current_mtime > self.last_modified[target_file]:
                        print(f"\n🔄 Change detected in {target_file}!")
                        self.last_modified[target_file] = current_mtime
                        
                        # Re-run tests
                        self.runner.discover_and_test(target_file)
                
                # Wait before next check
                asyncio.run(asyncio.sleep(interval))
                
        except KeyboardInterrupt:
            print("\n👋 Stopping file watcher...")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point for dynamic testing"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Dynamic Test Generator for Bot')
    parser.add_argument('--file', default='main.py', help='Target file to test')
    parser.add_argument('--config', default='test_config.json', help='Configuration file')
    parser.add_argument('--watch', action='store_true', help='Watch mode - auto re-run on changes')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--save-results', action='store_true', help='Save results to JSON')
    
    args = parser.parse_args()
    
    # Load configuration
    config = ConfigLoader.load_config(args.config)
    if args.verbose:
        config.verbose = True
    
    # Create runner
    runner = DynamicTestRunner(args.config)
    
    if args.watch:
        # Watch mode
        watcher = FileWatcher(runner)
        watcher.watch(args.file)
    else:
        # Single run
        results = runner.discover_and_test(args.file)
        
        if args.save_results:
            runner.save_results()
    
    # Return exit code based on results
    if results['failed'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()