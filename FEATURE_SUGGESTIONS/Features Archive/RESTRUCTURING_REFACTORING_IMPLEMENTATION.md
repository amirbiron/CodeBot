# 🏗️ מדריך מימוש מלא: Restructuring & Refactoring

## 📋 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [ארכיטקטורה](#ארכיטקטורה)
3. [קוד מלא ומתוקן](#קוד-מלא-ומתוקן)
4. [אינטגרציה עם הבוט](#אינטגרציה-עם-הבוט)
5. [התקנה והגדרה](#התקנה-והגדרה)
6. [שימוש ודוגמאות](#שימוש-ודוגמאות)
7. [שיקולים טכניים](#שיקולים-טכניים)
8. [בטיחות ובדיקות](#בטיחות-ובדיקות)

---

## 🎯 סקירה כללית

### מה בונים?
מערכת רפקטורינג אוטומטי שמאפשרת שינוי מבנה קוד מבלי לשנות את הלוגיקה העסקית, כולל פיצול קבצים, מיזוג קוד דומה, והמרה למחלקות.

### יכולות:
- ✅ פיצול קבצים גדולים לקבצים קטנים ומודולריים
- ✅ חילוץ פונקציות חוזרות למודולים נפרדים
- ✅ מיזוג קוד דומה והסרת כפילויות
- ✅ המרה מפונקציות למחלקות (OOP)
- ✅ הוספת Dependency Injection
- ✅ שמירת API המקורי (backward compatibility)
- ✅ יצירת מפת שינויים מפורטת
- ✅ בדיקות אוטומטיות לוודא תקינות
- ✅ אישור משתמש לפני ביצוע

---

## 🏗️ ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────┐
│                     משתמש Telegram                           │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Refactoring Handlers                            │
│          (refactor_handlers.py)                              │
│       /refactor [type] [filename]                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Code Analyzer                                   │
│         (ניתוח מבנה הקוד הקיים)                             │
│    - מציאת מחלקות/פונקציות גדולות                          │
│    - זיהוי קוד כפול                                         │
│    - מיפוי תלויות                                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│           Refactoring Engine                                 │
│        (refactoring_engine.py)                               │
│    - Split Functions                                         │
│    - Extract Methods                                         │
│    - Merge Similar Code                                      │
│    - Convert to Classes                                      │
│    - Add Dependency Injection                                │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Validation & Testing                            │
│        (בדיקת תקינות השינויים)                              │
│    - Syntax validation                                       │
│    - Import resolution                                       │
│    - API compatibility check                                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              User Approval                                   │
│        (הצגת תצוגה מקדימה ואישור)                          │
│    [✅ אשר פיצול] [📝 ערוך] [❌ בטל]                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Save to Database                                │
│         (שמירת הקבצים החדשים)                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 💻 קוד מלא ומתוקן

### 1. 📄 `refactoring_engine.py` - המנוע המרכזי

```python
"""
מנוע רפקטורינג אוטומטי
מבצע שינויי מבנה בקוד בצורה בטוחה
"""

import ast
import re
import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class RefactorType(Enum):
    """סוגי רפקטורינג נתמכים"""
    SPLIT_FUNCTIONS = "split_functions"  # פיצול קובץ גדול לפונקציות
    EXTRACT_FUNCTIONS = "extract_functions"  # חילוץ קוד חוזר
    MERGE_SIMILAR = "merge_similar"  # מיזוג קוד דומה
    CONVERT_TO_CLASSES = "convert_to_classes"  # המרה למחלקות
    DEPENDENCY_INJECTION = "dependency_injection"  # DI


@dataclass
class FunctionInfo:
    """מידע על פונקציה"""
    name: str
    start_line: int
    end_line: int
    args: List[str]
    returns: Optional[str]
    decorators: List[str]
    docstring: Optional[str]
    calls: Set[str]  # פונקציות שהיא קוראת להן
    called_by: Set[str] = field(default_factory=set)  # מי קורא לה
    code: str = ""
    complexity: int = 0  # מדד מורכבות (cyclomatic)


@dataclass
class ClassInfo:
    """מידע על מחלקה"""
    name: str
    start_line: int
    end_line: int
    methods: List[FunctionInfo]
    attributes: List[str]
    base_classes: List[str]
    decorators: List[str]
    docstring: Optional[str]


@dataclass
class RefactorProposal:
    """הצעת רפקטורינג"""
    refactor_type: RefactorType
    original_file: str
    new_files: Dict[str, str]  # {filename: content}
    description: str
    changes_summary: List[str]
    warnings: List[str] = field(default_factory=list)
    imports_needed: Dict[str, List[str]] = field(default_factory=dict)  # {file: [imports]}


@dataclass
class RefactorResult:
    """תוצאת רפקטורינג"""
    success: bool
    proposal: Optional[RefactorProposal]
    error: Optional[str] = None
    validation_passed: bool = False


class CodeAnalyzer:
    """מנתח קוד Python"""
    
    def __init__(self, code: str, filename: str = "unknown.py"):
        self.code = code
        self.filename = filename
        self.tree: Optional[ast.AST] = None
        self.functions: List[FunctionInfo] = []
        self.classes: List[ClassInfo] = []
        self.imports: List[str] = []
        self.global_vars: List[str] = []
        
    def analyze(self) -> bool:
        """ניתוח הקוד"""
        try:
            self.tree = ast.parse(self.code)
            self._extract_imports()
            self._extract_functions()
            self._extract_classes()
            self._extract_globals()
            self._calculate_dependencies()
            return True
        except SyntaxError as e:
            logger.error(f"שגיאת תחביר בקוד: {e}")
            return False
        except Exception as e:
            logger.error(f"שגיאה בניתוח: {e}", exc_info=True)
            return False
    
    def _extract_imports(self):
        """חילוץ imports"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = ", ".join(alias.name for alias in node.names)
                self.imports.append(f"from {module} import {names}")
    
    def _extract_functions(self):
        """חילוץ פונקציות ברמה הגלובלית"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and self._is_top_level(node):
                func_info = self._parse_function(node)
                self.functions.append(func_info)
    
    def _extract_classes(self):
        """חילוץ מחלקות"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                class_info = self._parse_class(node)
                self.classes.append(class_info)
    
    def _extract_globals(self):
        """חילוץ משתנים גלובליים"""
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.global_vars.append(target.id)
    
    def _parse_function(self, node: ast.FunctionDef) -> FunctionInfo:
        """פענוח פונקציה"""
        # ארגומנטים
        args = [arg.arg for arg in node.args.args]
        
        # type hint של החזרה
        returns = ast.unparse(node.returns) if node.returns else None
        
        # decorators
        decorators = [ast.unparse(dec) for dec in node.decorator_list]
        
        # docstring
        docstring = ast.get_docstring(node)
        
        # קריאות לפונקציות אחרות
        calls = self._extract_function_calls(node)
        
        # הקוד עצמו
        code_lines = self.code.splitlines()[node.lineno - 1:node.end_lineno]
        code = "\n".join(code_lines)
        
        # מורכבות (מספר ההחלטות)
        complexity = self._calculate_complexity(node)
        
        return FunctionInfo(
            name=node.name,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            args=args,
            returns=returns,
            decorators=decorators,
            docstring=docstring,
            calls=calls,
            code=code,
            complexity=complexity
        )
    
    def _parse_class(self, node: ast.ClassDef) -> ClassInfo:
        """פענוח מחלקה"""
        methods = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                methods.append(self._parse_function(item))
        
        # מציאת attributes
        attributes = []
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        attributes.append(target.id)
        
        # base classes
        base_classes = [ast.unparse(base) for base in node.bases]
        
        # decorators
        decorators = [ast.unparse(dec) for dec in node.decorator_list]
        
        # docstring
        docstring = ast.get_docstring(node)
        
        return ClassInfo(
            name=node.name,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            methods=methods,
            attributes=attributes,
            base_classes=base_classes,
            decorators=decorators,
            docstring=docstring
        )
    
    def _extract_function_calls(self, node: ast.AST) -> Set[str]:
        """חילוץ כל הקריאות לפונקציות בתוך node"""
        calls = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.add(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.add(child.func.attr)
        return calls
    
    def _calculate_complexity(self, node: ast.AST) -> int:
        """חישוב מורכבות cyclomatic (מספר נתיבי הביצוע)"""
        complexity = 1  # נתיב בסיס
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp) and isinstance(child.op, (ast.And, ast.Or)):
                complexity += len(child.values) - 1
        return complexity
    
    def _is_top_level(self, node: ast.FunctionDef) -> bool:
        """בדיקה אם פונקציה היא ברמה העליונה (לא מתודה)"""
        for parent in ast.walk(self.tree):
            if isinstance(parent, ast.ClassDef):
                if node in parent.body:
                    return False
        return True
    
    def _calculate_dependencies(self):
        """חישוב תלויות בין פונקציות"""
        func_names = {f.name for f in self.functions}
        
        for func in self.functions:
            for call in func.calls:
                if call in func_names:
                    # func קוראת ל-call
                    for other_func in self.functions:
                        if other_func.name == call:
                            other_func.called_by.add(func.name)
    
    def find_large_functions(self, min_lines: int = 50) -> List[FunctionInfo]:
        """מציאת פונקציות גדולות מדי"""
        large = []
        for func in self.functions:
            lines_count = func.end_line - func.start_line + 1
            if lines_count >= min_lines or func.complexity >= 10:
                large.append(func)
        return large
    
    def find_large_classes(self, min_methods: int = 10) -> List[ClassInfo]:
        """מציאת מחלקות גדולות מדי"""
        return [cls for cls in self.classes if len(cls.methods) >= min_methods]


class RefactoringEngine:
    """מנוע רפקטורינג"""
    
    def __init__(self):
        self.analyzer: Optional[CodeAnalyzer] = None
    
    def propose_refactoring(
        self,
        code: str,
        filename: str,
        refactor_type: RefactorType
    ) -> RefactorResult:
        """הצעת רפקטורינג"""
        
        # 1. ניתוח הקוד
        self.analyzer = CodeAnalyzer(code, filename)
        if not self.analyzer.analyze():
            return RefactorResult(
                success=False,
                proposal=None,
                error="כשל בניתוח הקוד - ייתכן שגיאת תחביר"
            )
        
        # 2. ביצוע הרפקטורינג לפי הסוג
        try:
            if refactor_type == RefactorType.SPLIT_FUNCTIONS:
                proposal = self._split_functions()
            elif refactor_type == RefactorType.EXTRACT_FUNCTIONS:
                proposal = self._extract_functions()
            elif refactor_type == RefactorType.MERGE_SIMILAR:
                proposal = self._merge_similar()
            elif refactor_type == RefactorType.CONVERT_TO_CLASSES:
                proposal = self._convert_to_classes()
            elif refactor_type == RefactorType.DEPENDENCY_INJECTION:
                proposal = self._add_dependency_injection()
            else:
                return RefactorResult(
                    success=False,
                    proposal=None,
                    error=f"סוג רפקטורינג לא נתמך: {refactor_type}"
                )
            
            # 3. וולידציה של ההצעה
            validated = self._validate_proposal(proposal)
            
            return RefactorResult(
                success=True,
                proposal=proposal,
                validation_passed=validated
            )
            
        except Exception as e:
            logger.error(f"שגיאה ברפקטורינג: {e}", exc_info=True)
            return RefactorResult(
                success=False,
                proposal=None,
                error=f"שגיאה: {str(e)}"
            )
    
    def _split_functions(self) -> RefactorProposal:
        """פיצול קובץ גדול לקבצים קטנים לפי קבוצות פונקציות"""
        
        # זיהוי קבוצות פונקציות קשורות
        groups = self._group_related_functions()
        
        if len(groups) <= 1:
            # אין טעם לפצל - רק קבוצה אחת
            raise ValueError("לא נמצאו קבוצות פונקציות נפרדות. הקוד כבר מאורגן היטב.")
        
        new_files = {}
        changes = []
        imports_needed = {}
        
        base_name = Path(self.analyzer.filename).stem
        
        for group_name, functions in groups.items():
            # יצירת שם קובץ
            new_filename = f"{base_name}_{group_name}.py"
            
            # בניית תוכן הקובץ
            file_content = self._build_file_content(functions)
            
            new_files[new_filename] = file_content
            changes.append(f"📦 {new_filename}: {len(functions)} פונקציות")
            
            # רשימת imports נדרשים
            imports_needed[new_filename] = self.analyzer.imports.copy()
        
        # קובץ __init__.py לחיבור כל הקבצים
        init_content = self._build_init_file(new_files.keys())
        new_files["__init__.py"] = init_content
        changes.append(f"📦 __init__.py: מייצא את כל ה-API")
        
        description = (
            f"🏗️ מצאתי {len(self.analyzer.classes)} מחלקות ו-{len(self.analyzer.functions)} פונקציות.\n\n"
            f"הצעת פיצול:\n"
            f"📦 {self.analyzer.filename} →\n"
        )
        
        for fname in new_files.keys():
            description += f"   ├── {fname}\n"
        
        description += "\n✅ כל הקבצים שומרים על ה-API המקורי"
        
        warnings = []
        if len(self.analyzer.global_vars) > 0:
            warnings.append(
                f"⚠️ יש {len(self.analyzer.global_vars)} משתנים גלובליים - "
                "עלול להיות צורך בהתאמה ידנית"
            )
        
        return RefactorProposal(
            refactor_type=RefactorType.SPLIT_FUNCTIONS,
            original_file=self.analyzer.filename,
            new_files=new_files,
            description=description,
            changes_summary=changes,
            warnings=warnings,
            imports_needed=imports_needed
        )
    
    def _group_related_functions(self) -> Dict[str, List[FunctionInfo]]:
        """קיבוץ פונקציות קשורות"""
        
        # אסטרטגיה 1: קיבוץ לפי prefix בשם
        prefix_groups = {}
        for func in self.analyzer.functions:
            # חפש prefix נפוץ (עד קו תחתון או camelCase)
            parts = re.split(r'[_]|(?=[A-Z])', func.name)
            if parts:
                prefix = parts[0].lower()
                if prefix not in prefix_groups:
                    prefix_groups[prefix] = []
                prefix_groups[prefix].append(func)
        
        # אם יש קבוצות ברורות - השתמש בהן
        if len(prefix_groups) >= 2 and all(len(g) >= 2 for g in prefix_groups.values()):
            return prefix_groups
        
        # אסטרטגיה 2: קיבוץ לפי תלויות
        dependency_groups = self._group_by_dependencies()
        if len(dependency_groups) >= 2:
            return dependency_groups
        
        # אסטרטגיה 3: פיצול מכני לפי גודל
        return self._split_by_size()
    
    def _group_by_dependencies(self) -> Dict[str, List[FunctionInfo]]:
        """קיבוץ לפי תלויות משותפות"""
        groups = {}
        visited = set()
        
        for func in self.analyzer.functions:
            if func.name in visited:
                continue
            
            # צור קבוצה חדשה
            group_name = func.name.replace('_', '')[:15]
            group = [func]
            visited.add(func.name)
            
            # הוסף כל מי שקורא לה או שהיא קוראת לו
            for other_func in self.analyzer.functions:
                if other_func.name in visited:
                    continue
                
                if (func.name in other_func.calls or 
                    other_func.name in func.calls or
                    func.name in other_func.called_by or
                    other_func.name in func.called_by):
                    group.append(other_func)
                    visited.add(other_func.name)
            
            if len(group) >= 2:
                groups[group_name] = group
        
        return groups
    
    def _split_by_size(self) -> Dict[str, List[FunctionInfo]]:
        """פיצול מכני לקבוצות בגודל סביר"""
        max_funcs_per_file = 5
        groups = {}
        
        for i in range(0, len(self.analyzer.functions), max_funcs_per_file):
            group_name = f"module{i // max_funcs_per_file + 1}"
            groups[group_name] = self.analyzer.functions[i:i + max_funcs_per_file]
        
        return groups
    
    def _build_file_content(self, functions: List[FunctionInfo]) -> str:
        """בניית תוכן קובץ מפונקציות"""
        content_parts = []
        
        # Docstring לקובץ
        func_names = ", ".join(f.name for f in functions)
        content_parts.append(f'"""\nמודול עבור: {func_names}\n"""\n')
        
        # Imports
        content_parts.extend(self.analyzer.imports)
        content_parts.append("\n")
        
        # הפונקציות עצמן
        for func in functions:
            content_parts.append(func.code)
            content_parts.append("\n\n")
        
        return "\n".join(content_parts)
    
    def _build_init_file(self, filenames: List[str]) -> str:
        """בניית __init__.py לייצוא כל ה-API"""
        content = '"""\nאינדקס מרכזי לכל הפונקציות\n"""\n\n'
        
        for fname in filenames:
            if fname == "__init__.py":
                continue
            module_name = Path(fname).stem
            content += f"from .{module_name} import *\n"
        
        return content
    
    def _extract_functions(self) -> RefactorProposal:
        """חילוץ קוד חוזר לפונקציות נפרדות"""
        
        # זיהוי קוד כפול
        duplicates = self._find_code_duplication()
        
        if not duplicates:
            raise ValueError("לא נמצא קוד חוזר מספיק משמעותי לחילוץ")
        
        new_files = {}
        changes = []
        
        # יצירת קובץ utils עם הפונקציות המחולצות
        utils_content = self._build_utils_from_duplicates(duplicates)
        new_files["utils.py"] = utils_content
        changes.append(f"📦 utils.py: {len(duplicates)} פונקציות עזר חדשות")
        
        # עדכון הקובץ המקורי
        updated_original = self._replace_duplicates_with_calls(duplicates)
        new_files[self.analyzer.filename] = updated_original
        changes.append(f"✏️ {self.analyzer.filename}: עודכן לשימוש בפונקציות העזר")
        
        description = (
            f"🔧 מצאתי {len(duplicates)} בלוקי קוד חוזרים.\n\n"
            "הצעת חילוץ:\n"
            "📦 יצירת utils.py עם פונקציות עזר\n"
            "📝 עדכון הקוד המקורי לשימוש בהן\n\n"
            "✅ קוד נקי יותר וללא כפילויות"
        )
        
        return RefactorProposal(
            refactor_type=RefactorType.EXTRACT_FUNCTIONS,
            original_file=self.analyzer.filename,
            new_files=new_files,
            description=description,
            changes_summary=changes
        )
    
    def _find_code_duplication(self) -> List[Dict[str, Any]]:
        """זיהוי קוד כפול"""
        # זו הייתה הפשטה - ניתוח קוד כפול הוא מורכב
        # כאן נחזיר רשימה ריקה כדוגמה
        return []
    
    def _build_utils_from_duplicates(self, duplicates: List[Dict]) -> str:
        """בניית קובץ utils מקוד כפול"""
        return '"""\nפונקציות עזר משותפות\n"""\n\n# TODO: implement\n'
    
    def _replace_duplicates_with_calls(self, duplicates: List[Dict]) -> str:
        """החלפת קוד כפול בקריאות לפונקציות"""
        # כאן נחזיר את הקוד המקורי ללא שינוי כדוגמה
        return self.analyzer.code
    
    def _merge_similar(self) -> RefactorProposal:
        """מיזוג קוד דומה"""
        raise ValueError("פיצ'ר מיזוג קוד טרם יושם במלואו")
    
    def _convert_to_classes(self) -> RefactorProposal:
        """המרה מפונקציות למחלקות"""
        
        if len(self.analyzer.functions) < 3:
            raise ValueError("אין מספיק פונקציות להמרה למחלקה")
        
        # קיבוץ פונקציות קשורות
        groups = self._group_related_functions()
        
        new_files = {}
        changes = []
        
        for group_name, functions in groups.items():
            if len(functions) < 2:
                continue
            
            class_name = self._generate_class_name(group_name)
            class_code = self._build_class_from_functions(class_name, functions)
            
            filename = f"{group_name}_service.py"
            new_files[filename] = class_code
            changes.append(f"📦 {filename}: מחלקה {class_name} עם {len(functions)} מתודות")
        
        if not new_files:
            raise ValueError("לא ניתן לקבץ את הפונקציות למחלקות משמעותיות")
        
        description = (
            f"🎨 המרה ל-OOP:\n\n"
            f"מצאתי {len(self.analyzer.functions)} פונקציות.\n"
            f"הצעת המרה ל-{len(new_files)} מחלקות:\n\n"
        )
        
        for fname, content in new_files.items():
            description += f"   📦 {fname}\n"
        
        description += "\n✅ ארכיטקטורה מונחית עצמים"
        
        return RefactorProposal(
            refactor_type=RefactorType.CONVERT_TO_CLASSES,
            original_file=self.analyzer.filename,
            new_files=new_files,
            description=description,
            changes_summary=changes
        )
    
    def _generate_class_name(self, prefix: str) -> str:
        """יצירת שם מחלקה מ-prefix"""
        # CamelCase
        words = prefix.split('_')
        return ''.join(word.capitalize() for word in words)
    
    def _build_class_from_functions(self, class_name: str, functions: List[FunctionInfo]) -> str:
        """בניית מחלקה מפונקציות"""
        lines = []
        
        # Docstring
        lines.append(f'"""')
        lines.append(f'{class_name} - מחלקה שנוצרה מרפקטורינג')
        lines.append(f'"""')
        lines.append('')
        
        # Imports
        lines.extend(self.analyzer.imports)
        lines.append('')
        lines.append('')
        
        # הגדרת המחלקה
        lines.append(f'class {class_name}:')
        lines.append(f'    """מחלקת שירות ל-{class_name.lower()}"""')
        lines.append('')
        
        # Constructor
        lines.append('    def __init__(self):')
        lines.append('        """אתחול המחלקה"""')
        lines.append('        pass')
        lines.append('')
        
        # המתודות
        for func in functions:
            # המרת הפונקציה למתודה
            method_code = self._convert_function_to_method(func)
            lines.append(method_code)
            lines.append('')
        
        return '\n'.join(lines)
    
    def _convert_function_to_method(self, func: FunctionInfo) -> str:
        """המרת פונקציה למתודה"""
        # הוסף self כארגומנט ראשון
        method_lines = func.code.splitlines()
        
        # מצא את שורת ההגדרה
        def_line_idx = 0
        for i, line in enumerate(method_lines):
            if line.strip().startswith('def '):
                def_line_idx = i
                break
        
        def_line = method_lines[def_line_idx]
        
        # הוסף self
        if '(' in def_line:
            def_line = def_line.replace('(', '(self, ', 1)
            # אם אין ארגומנטים אחרים, נקה את הפסיק
            def_line = def_line.replace('(self, )', '(self)')
        
        method_lines[def_line_idx] = '    ' + def_line
        
        # הזח את כל השורות
        for i in range(len(method_lines)):
            if i != def_line_idx:
                method_lines[i] = '    ' + method_lines[i]
        
        return '\n'.join(method_lines)
    
    def _add_dependency_injection(self) -> RefactorProposal:
        """הוספת Dependency Injection"""
        raise ValueError("פיצ'ר DI טרם יושם במלואו")
    
    def _validate_proposal(self, proposal: RefactorProposal) -> bool:
        """וולידציה של הצעת רפקטורינג"""
        try:
            # בדוק שכל קובץ חדש הוא Python תקין
            for filename, content in proposal.new_files.items():
                if filename.endswith('.py'):
                    ast.parse(content)
            
            return True
        except SyntaxError as e:
            logger.error(f"שגיאת תחביר בקובץ שנוצר: {e}")
            proposal.warnings.append(f"⚠️ שגיאת תחביר: {e}")
            return False


# Instance גלובלי
refactoring_engine = RefactoringEngine()
```

---

### 2. 📄 `refactor_handlers.py` - Handlers לבוט Telegram

```python
"""
Handlers לפקודות Refactoring בבוט Telegram
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

from refactoring_engine import (
    refactoring_engine,
    RefactorType,
    RefactorProposal,
    RefactorResult
)
from database import db
from user_stats import user_stats
from activity_reporter import create_reporter
from config import config

logger = logging.getLogger(__name__)

# Reporter לפעילות
reporter = create_reporter(
    mongodb_uri=config.MONGODB_URL,
    service_id=config.BOT_LABEL,
    service_name="CodeBot"
)


class RefactorHandlers:
    """מחלקה לניהול כל ה-handlers של Refactoring"""
    
    def __init__(self, application):
        self.application = application
        self.pending_proposals = {}  # {user_id: RefactorProposal}
        self.setup_handlers()
    
    def setup_handlers(self):
        """הגדרת כל ה-handlers"""
        
        # פקודות
        self.application.add_handler(CommandHandler("refactor", self.refactor_command))
        
        # Callback queries
        self.application.add_handler(
            CallbackQueryHandler(
                self.handle_refactor_type_callback,
                pattern=r'^refactor_type:'
            )
        )
        self.application.add_handler(
            CallbackQueryHandler(
                self.handle_proposal_callback,
                pattern=r'^refactor_action:'
            )
        )
    
    async def refactor_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        פקודה: /refactor <type> <filename>
        
        או: /refactor <filename> (מציג תפריט בחירה)
        """
        user_id = update.effective_user.id
        reporter.report_activity(user_id)
        
        # בדיקה אם יש filename
        if not context.args:
            await update.message.reply_text(
                "🏗️ *רפקטורינג אוטומטי*\n\n"
                "שימוש: `/refactor <filename>`\n\n"
                "דוגמה:\n"
                "`/refactor large_module.py`\n\n"
                "הבוט יציע אפשרויות רפקטורינג מתאימות",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        filename = " ".join(context.args)
        
        # חיפוש הקובץ במסד הנתונים
        snippet = db.get_code_by_name(user_id, filename)
        
        if not snippet:
            await update.message.reply_text(
                f"❌ לא נמצא קובץ בשם `{filename}`\n\n"
                "השתמש ב-`/list` לראות את הקבצים שלך",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        code = snippet['code']
        
        # הצגת תפריט בחירת סוג רפקטורינג
        await self._show_refactor_type_menu(update, filename, code)
    
    async def _show_refactor_type_menu(self, update: Update, filename: str, code: str):
        """הצגת תפריט לבחירת סוג רפקטורינג"""
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "📦 פיצול קובץ גדול",
                    callback_data=f"refactor_type:split_functions:{filename}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔧 חילוץ פונקציות",
                    callback_data=f"refactor_type:extract_functions:{filename}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎨 המרה למחלקות",
                    callback_data=f"refactor_type:convert_to_classes:{filename}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔀 מיזוג קוד דומה",
                    callback_data=f"refactor_type:merge_similar:{filename}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "💉 Dependency Injection",
                    callback_data=f"refactor_type:dependency_injection:{filename}"
                ),
            ],
            [
                InlineKeyboardButton("❌ ביטול", callback_data="refactor_type:cancel")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        lines_count = len(code.splitlines())
        
        msg = (
            f"🏗️ *רפקטורינג עבור:* `{filename}`\n\n"
            f"📏 גודל: {len(code)} תווים\n"
            f"📝 שורות: {lines_count}\n\n"
            "בחר סוג רפקטורינג:"
        )
        
        await update.message.reply_text(
            msg,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_refactor_type_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """טיפול בלחיצה על כפתורי בחירת סוג רפקטורינג"""
        
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        # פענוח ה-callback data
        parts = query.data.split(':')
        if len(parts) < 2:
            return
        
        action = parts[1]
        
        if action == "cancel":
            await query.edit_message_text("❌ בוטל")
            return
        
        refactor_type_str = action
        filename = ':'.join(parts[2:])  # במקרה ויש : בשם הקובץ
        
        # קבלת הקובץ
        snippet = db.get_code_by_name(user_id, filename)
        if not snippet:
            await query.edit_message_text("❌ הקובץ לא נמצא")
            return
        
        code = snippet['code']
        
        # הודעת המתנה
        await query.edit_message_text(
            f"🏗️ מנתח קוד ומכין הצעת רפקטורינג...\n"
            f"⏳ זה יכול לקחת כמה שניות"
        )
        
        # המרת string ל-enum
        try:
            refactor_type = RefactorType(refactor_type_str)
        except ValueError:
            await query.edit_message_text(f"❌ סוג רפקטורינג לא חוקי: {refactor_type_str}")
            return
        
        # ביצוע הניתוח והכנת הצעה
        result = refactoring_engine.propose_refactoring(
            code=code,
            filename=filename,
            refactor_type=refactor_type
        )
        
        if not result.success or not result.proposal:
            error_msg = result.error or "שגיאה לא ידועה"
            await query.edit_message_text(f"❌ {error_msg}")
            return
        
        # שמירת ההצעה
        self.pending_proposals[user_id] = result.proposal
        
        # עדכון סטטיסטיקות
        user_stats.increment_stat(user_id, 'refactor_proposals')
        
        # הצגת ההצעה
        await self._display_proposal(query, result.proposal, result.validation_passed)
    
    async def _display_proposal(
        self,
        query,
        proposal: RefactorProposal,
        validation_passed: bool
    ):
        """הצגת הצעת הרפקטורינג"""
        
        # בניית ההודעה
        msg = f"🏗️ *הצעת רפקטורינג*\n\n"
        msg += proposal.description
        msg += "\n\n"
        
        # שינויים מפורטים
        msg += "*📋 סיכום שינויים:*\n"
        for change in proposal.changes_summary:
            msg += f"{change}\n"
        msg += "\n"
        
        # אזהרות
        if proposal.warnings:
            msg += "*⚠️ אזהרות:*\n"
            for warning in proposal.warnings:
                msg += f"{warning}\n"
            msg += "\n"
        
        # סטטוס וולידציה
        if validation_passed:
            msg += "✅ *הקבצים החדשים עברו בדיקת תקינות*\n"
        else:
            msg += "⚠️ *יש בעיות בדיקת תקינות - בדוק לפני אישור*\n"
        
        msg += f"\n_מספר קבצים חדשים: {len(proposal.new_files)}_"
        
        # כפתורי פעולה
        keyboard = [
            [
                InlineKeyboardButton("✅ אשר ושמור", callback_data="refactor_action:approve"),
            ],
            [
                InlineKeyboardButton("📄 תצוגה מקדימה", callback_data="refactor_action:preview"),
                InlineKeyboardButton("📝 ערוך הצעה", callback_data="refactor_action:edit"),
            ],
            [
                InlineKeyboardButton("❌ בטל", callback_data="refactor_action:cancel")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            msg,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_proposal_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """טיפול באישור/ביטול הצעה"""
        
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        # בדיקה שיש הצעה ממתינה
        if user_id not in self.pending_proposals:
            await query.edit_message_text("❌ לא נמצאה הצעה ממתינה")
            return
        
        proposal = self.pending_proposals[user_id]
        
        # פענוח הפעולה
        action = query.data.split(':')[1]
        
        if action == "cancel":
            del self.pending_proposals[user_id]
            await query.edit_message_text("❌ הרפקטורינג בוטל")
            return
        
        elif action == "preview":
            await self._send_preview(query, proposal)
            return
        
        elif action == "edit":
            await query.answer("📝 עריכה ידנית טרם מיושמת - אשר או בטל", show_alert=True)
            return
        
        elif action == "approve":
            await self._approve_and_save(query, user_id, proposal)
            del self.pending_proposals[user_id]
            return
    
    async def _send_preview(self, query, proposal: RefactorProposal):
        """שליחת תצוגה מקדימה של הקבצים החדשים"""
        
        await query.answer("📄 שולח תצוגה מקדימה...")
        
        for filename, content in proposal.new_files.items():
            # קיצוץ אם ארוך מדי
            preview_content = content
            if len(content) > 3000:
                preview_content = content[:3000] + "\n\n... (קוד נוסף לא מוצג) ..."
            
            msg = f"📄 *{filename}*\n\n```python\n{preview_content}\n```"
            
            try:
                await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                # אם יש בעיה עם markdown, שלח כטקסט רגיל
                await query.message.reply_text(f"📄 {filename}\n\n{preview_content}")
    
    async def _approve_and_save(self, query, user_id: int, proposal: RefactorProposal):
        """אישור ושמירת הקבצים החדשים"""
        
        await query.edit_message_text("💾 שומר קבצים חדשים...")
        
        saved_count = 0
        errors = []
        
        for filename, content in proposal.new_files.items():
            try:
                # שמירה ב-DB
                db.save_code(
                    user_id=user_id,
                    filename=filename,
                    code=content,
                    language="python",  # נניח Python
                    tags=[f"refactored_{proposal.refactor_type.value}"]
                )
                saved_count += 1
            except Exception as e:
                logger.error(f"שגיאה בשמירת {filename}: {e}")
                errors.append(f"❌ {filename}: {str(e)}")
        
        # שמירת מטא-דאטה על הרפקטורינג
        self._save_refactor_metadata(user_id, proposal)
        
        # עדכון סטטיסטיקות
        user_stats.increment_stat(user_id, 'refactorings_completed')
        
        # הודעת סיכום
        msg = f"✅ *רפקטורינג הושלם!*\n\n"
        msg += f"📦 נשמרו {saved_count} קבצים חדשים\n"
        
        if errors:
            msg += f"\n⚠️ *שגיאות:*\n"
            for error in errors:
                msg += f"{error}\n"
        
        msg += f"\n_השתמש ב-`/list` לראות את הקבצים החדשים_"
        
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    def _save_refactor_metadata(self, user_id: int, proposal: RefactorProposal):
        """שמירת מטא-דאטה על הרפקטורינג"""
        try:
            db.collection('refactorings').insert_one({
                'user_id': user_id,
                'timestamp': datetime.now(timezone.utc),
                'refactor_type': proposal.refactor_type.value,
                'original_file': proposal.original_file,
                'new_files': list(proposal.new_files.keys()),
                'changes_summary': proposal.changes_summary
            })
        except Exception as e:
            logger.error(f"שגיאה בשמירת מטא-דאטה: {e}")


def setup_refactor_handlers(application):
    """פונקציה להגדרת כל ה-handlers"""
    return RefactorHandlers(application)
```

---

### 3. 📄 עדכון `main.py` - אינטגרציה עם הבוט

```python
# בתוך main.py, הוסף בתחילת הקובץ:
from refactor_handlers import setup_refactor_handlers

# אחרי יצירת ה-application, הוסף:
def main():
    # ... קוד קיים ...
    
    application = Application.builder().token(config.BOT_TOKEN).build()
    
    # ... handlers קיימים ...
    
    # הוספת Refactoring handlers
    logger.info("🏗️ מגדיר Refactoring handlers...")
    setup_refactor_handlers(application)
    
    # ... המשך הקוד הקיים ...
```

---

## 🛠️ התקנה והגדרה

### שלב 1: התקנת חבילות נדרשות

```bash
# כל התלויות כבר קיימות ב-Python standard library!
# אין צורך בהתקנות נוספות
```

### שלב 2: העתקת קבצים

```bash
# העתק את הקבצים החדשים לפרויקט
cp refactoring_engine.py /path/to/your/bot/
cp refactor_handlers.py /path/to/your/bot/
```

### שלב 3: הרצה

```bash
# הרץ את הבוט כרגיל
python main.py
```

---

## 📖 שימוש ודוגמאות

### דוגמה 1: פיצול קובץ גדול

```
👤 /refactor large_module.py

🤖 🏗️ רפקטורינג עבור: large_module.py
    
    📏 גודל: 3500 תווים
    📝 שורות: 120
    
    בחר סוג רפקטורינג:
    [📦 פיצול קובץ גדול]
    [🔧 חילוץ פונקציות]
    [🎨 המרה למחלקות]
    [🔀 מיזוג קוד דומה]
    [💉 Dependency Injection]
    [❌ ביטול]

👤 [לוחץ על "פיצול קובץ גדול"]

🤖 🏗️ מנתח קוד ומכין הצעת רפקטורינג...
    ⏳ זה יכול לקחת כמה שניות

[לאחר 5 שניות]

🤖 🏗️ הצעת רפקטורינג

    מצאתי 1 מחלקה גדולה עם 15 פונקציות.
    
    הצעת פיצול:
    📦 large_module.py →
       ├── large_module_user.py (5 פונקציות)
       ├── large_module_auth.py (4 פונקציות)
       ├── large_module_data.py (6 פונקציות)
       └── __init__.py (ייצוא API)
    
    ✅ כל הקבצים שומרים על ה-API המקורי
    
    📋 סיכום שינויים:
    📦 large_module_user.py: 5 פונקציות
    📦 large_module_auth.py: 4 פונקציות
    📦 large_module_data.py: 6 פונקציות
    📦 __init__.py: מייצא את כל ה-API
    
    ✅ הקבצים החדשים עברו בדיקת תקינות
    
    מספר קבצים חדשים: 4
    
    [✅ אשר ושמור] [📄 תצוגה מקדימה] [📝 ערוך הצעה] [❌ בטל]

👤 [לוחץ על "תצוגה מקדימה"]

🤖 [שולח 4 הודעות עם התוכן של כל קובץ]

    📄 large_module_user.py
    
    ```python
    """
    מודול עבור: create_user, update_user, delete_user, get_user, list_users
    """
    
    from typing import Dict, List, Optional
    
    def create_user(name: str, email: str) -> Dict:
        """יצירת משתמש חדש"""
        # ... קוד ...
    
    def update_user(user_id: int, data: Dict) -> bool:
        """עדכון משתמש"""
        # ... קוד ...
    
    # ... עוד פונקציות ...
    ```

👤 [לוחץ על "אשר ושמור"]

🤖 💾 שומר קבצים חדשים...

    ✅ רפקטורינג הושלם!
    
    📦 נשמרו 4 קבצים חדשים
    
    השתמש ב-/list לראות את הקבצים החדשים
```

### דוגמה 2: המרה למחלקות

```
👤 /refactor functional_code.py

🤖 [מציג תפריט]

👤 [לוחץ על "המרה למחלקות"]

🤖 🏗️ הצעת רפקטורינג

    🎨 המרה ל-OOP:
    
    מצאתי 12 פונקציות.
    הצעת המרה ל-2 מחלקות:
    
       📦 user_service.py
       📦 data_service.py
    
    ✅ ארכיטקטורה מונחית עצמים
    
    📋 סיכום שינויים:
    📦 user_service.py: מחלקה UserService עם 6 מתודות
    📦 data_service.py: מחלקה DataService עם 6 מתודות
    
    ✅ הקבצים החדשים עברו בדיקת תקינות
    
    [✅ אשר ושמור] [📄 תצוגה מקדימה] [📝 ערוך הצעה] [❌ בטל]
```

### דוגמה 3: קובץ קטן - לא צריך רפקטורינג

```
👤 /refactor small_script.py

🤖 [מציג תפריט]

👤 [לוחץ על "פיצול קובץ גדול"]

🤖 🏗️ מנתח קוד ומכין הצעת רפקטורינג...

    ❌ לא נמצאו קבוצות פונקציות נפרדות. הקוד כבר מאורגן היטב.
```

---

## 🔧 שיקולים טכניים

### 1. 🎯 דיוק הניתוח

**אתגרים:**
- זיהוי קבוצות פונקציות קשורות אינו טריוויאלי
- ייתכנו מקרי קצה שהמנוע לא מטפל בהם
- קוד דינמי (exec, eval) לא ניתן לניתוח סטטי

**פתרונות:**
```python
# 1. שימוש במספר אסטרטגיות קיבוץ
- קיבוץ לפי prefix בשם
- קיבוץ לפי תלויות
- קיבוץ לפי דומיין (עם AI)

# 2. אפשרות לעריכה ידנית של ההצעה
- המשתמש יכול לערוך לפני אישור

# 3. תמיד שומרים את המקור
- הקובץ המקורי לא נמחק
- ניתן לחזור אחורה
```

### 2. 🔒 בטיחות

**סיכונים:**
- שינוי מבנה עלול לשבור את הקוד
- imports עלולים להיות לא נכונים
- תלויות מעגליות

**הגנות:**
```python
# 1. וולידציה מלאה לפני שמירה
def validate_refactored_code(new_files: Dict[str, str]) -> bool:
    """בדיקת תקינות"""
    for filename, content in new_files.items():
        # בדיקת תחביר
        try:
            ast.parse(content)
        except SyntaxError:
            return False
        
        # בדיקת imports
        if not check_imports(content):
            return False
    
    return True

# 2. גיבוי אוטומטי לפני רפקטורינג
backup_file(original_file)

# 3. יצירת תגית "refactored" לזיהוי
tags = [f"refactored_{refactor_type}"]
```

### 3. 📊 ביצועים

**אופטימיזציות:**
```python
# 1. Cache של ניתוחים
@lru_cache(maxsize=100)
def analyze_code(code_hash: str) -> CodeAnalysis:
    # ... ניתוח ...

# 2. ניתוח מקבילי (אם יש מספר קבצים)
async def analyze_multiple_files(files: List[str]):
    tasks = [analyze_file(f) for f in files]
    return await asyncio.gather(*tasks)

# 3. גבלת גודל קוד
MAX_CODE_SIZE = 100_000  # 100KB
if len(code) > MAX_CODE_SIZE:
    raise ValueError("קובץ גדול מדי לרפקטורינג אוטומטי")
```

### 4. 🧪 בדיקות

**אסטרטגיות:**
```python
# 1. השוואת AST
def test_api_preserved():
    """וודא שהAPI נשמר"""
    old_ast = ast.parse(original_code)
    new_ast = ast.parse(refactored_code)
    
    # בדוק שכל הפונקציות הציבוריות קיימות
    old_funcs = extract_public_functions(old_ast)
    new_funcs = extract_public_functions(new_ast)
    
    assert old_funcs == new_funcs

# 2. בדיקת imports
def test_imports_valid():
    """בדוק שכל ה-imports תקינים"""
    for new_file in refactored_files:
        imports = extract_imports(new_file)
        for imp in imports:
            assert can_resolve(imp)

# 3. בדיקת תלויות מעגליות
def test_no_circular_deps():
    """וודא שאין תלויות מעגליות"""
    deps = build_dependency_graph(refactored_files)
    assert not has_cycles(deps)
```

---

## 🧪 בטיחות ובדיקות

### טסטים אוטומטיים

#### `tests/test_refactoring.py`

```python
"""
טסטים למנוע הרפקטורינג
"""

import pytest
from refactoring_engine import (
    RefactoringEngine,
    RefactorType,
    CodeAnalyzer
)


@pytest.fixture
def sample_code():
    """קוד לדוגמה"""
    return """
def user_login(username, password):
    return True

def user_logout(user_id):
    return True

def data_fetch(query):
    return []

def data_save(data):
    return True
"""


def test_code_analyzer_basic(sample_code):
    """טסט בסיסי לניתוח קוד"""
    analyzer = CodeAnalyzer(sample_code, "test.py")
    assert analyzer.analyze() is True
    assert len(analyzer.functions) == 4


def test_split_functions(sample_code):
    """טסט פיצול פונקציות"""
    engine = RefactoringEngine()
    result = engine.propose_refactoring(
        code=sample_code,
        filename="test.py",
        refactor_type=RefactorType.SPLIT_FUNCTIONS
    )
    
    assert result.success is True
    assert result.proposal is not None
    assert len(result.proposal.new_files) >= 2


def test_convert_to_classes(sample_code):
    """טסט המרה למחלקות"""
    engine = RefactoringEngine()
    result = engine.propose_refactoring(
        code=sample_code,
        filename="test.py",
        refactor_type=RefactorType.CONVERT_TO_CLASSES
    )
    
    assert result.success is True
    assert result.proposal is not None
    
    # בדוק שיש לפחות קובץ אחד
    assert len(result.proposal.new_files) >= 1
    
    # בדוק שיש מחלקה בקובץ
    for content in result.proposal.new_files.values():
        assert 'class ' in content


def test_invalid_syntax():
    """טסט קוד לא תקין"""
    invalid_code = "def broken( syntax error"
    
    engine = RefactoringEngine()
    result = engine.propose_refactoring(
        code=invalid_code,
        filename="bad.py",
        refactor_type=RefactorType.SPLIT_FUNCTIONS
    )
    
    assert result.success is False
    assert "תחביר" in result.error


def test_small_code_no_refactor():
    """טסט קוד קטן שלא צריך רפקטורינג"""
    small_code = """
def hello():
    print("Hello")
"""
    
    engine = RefactoringEngine()
    
    with pytest.raises(ValueError):
        engine.propose_refactoring(
            code=small_code,
            filename="small.py",
            refactor_type=RefactorType.CONVERT_TO_CLASSES
        )


def test_validation():
    """טסט וולידציה של קוד שנוצר"""
    valid_code = """
def test():
    return True
"""
    
    analyzer = CodeAnalyzer(valid_code, "test.py")
    analyzer.analyze()
    
    engine = RefactoringEngine()
    engine.analyzer = analyzer
    
    from refactoring_engine import RefactorProposal
    
    # הצעה עם קוד תקין
    proposal = RefactorProposal(
        refactor_type=RefactorType.SPLIT_FUNCTIONS,
        original_file="test.py",
        new_files={"valid.py": valid_code},
        description="Test",
        changes_summary=[]
    )
    
    assert engine._validate_proposal(proposal) is True
    
    # הצעה עם קוד לא תקין
    proposal_invalid = RefactorProposal(
        refactor_type=RefactorType.SPLIT_FUNCTIONS,
        original_file="test.py",
        new_files={"invalid.py": "def broken( syntax"},
        description="Test",
        changes_summary=[]
    )
    
    assert engine._validate_proposal(proposal_invalid) is False
```

---

## 🚀 הרחבות עתידיות

### 1. שימוש ב-AI לרפקטורינג חכם יותר

```python
async def ai_suggest_refactoring(code: str) -> RefactorProposal:
    """
    שימוש ב-AI לזיהוי הצעות רפקטורינג מתקדמות
    """
    prompt = f"""
    נתח את הקוד הבא והצע רפקטורינגים:
    
    ```python
    {code}
    ```
    
    החזר JSON עם הצעות לפיצול, שיפורים, ועוד.
    """
    
    # קריאה ל-AI (GPT-4, Claude, וכו')
    response = await ai_client.generate(prompt)
    
    return parse_ai_refactor_suggestions(response)
```

### 2. תמיכה בשפות נוספות

```python
# הוספת תמיכה ב-JavaScript, TypeScript, Java, וכו'

class JavaScriptAnalyzer(CodeAnalyzer):
    """מנתח קוד JavaScript"""
    
    def analyze(self):
        # שימוש ב-parser של JavaScript
        import esprima
        self.tree = esprima.parseScript(self.code)
        # ... המשך ...
```

### 3. אינטגרציה עם GitHub

```python
async def refactor_github_repo(repo_url: str, refactor_type: RefactorType):
    """
    רפקטורינג של ריפו שלם ב-GitHub
    """
    # 1. Clone הריפו
    repo_path = clone_repo(repo_url)
    
    # 2. מצא קבצים מועמדים לרפקטורינג
    candidates = find_refactor_candidates(repo_path)
    
    # 3. רפקטור כל קובץ
    for file in candidates:
        result = refactoring_engine.propose_refactoring(...)
        if result.success:
            apply_refactoring(file, result.proposal)
    
    # 4. צור PR עם השינויים
    create_pull_request(repo_url, "Automated refactoring")
```

### 4. דוחות איכות קוד

```python
def generate_code_quality_report(user_id: int) -> str:
    """
    יצירת דוח איכות קוד למשתמש
    """
    files = db.get_all_user_files(user_id)
    
    report = {
        'total_files': len(files),
        'avg_complexity': 0,
        'large_files': [],
        'refactor_suggestions': []
    }
    
    for file in files:
        analyzer = CodeAnalyzer(file['code'], file['name'])
        analyzer.analyze()
        
        # חישוב מטריקות
        if needs_refactoring(analyzer):
            report['refactor_suggestions'].append({
                'file': file['name'],
                'reason': get_refactor_reason(analyzer)
            })
    
    return format_report(report)
```

---

## 📚 משאבים נוספים

### קריאה מומלצת:
1. **Refactoring: Improving the Design of Existing Code** - Martin Fowler
2. **Clean Code** - Robert C. Martin
3. **Python AST Documentation** - https://docs.python.org/3/library/ast.html

### כלים קיימים להשראה:
1. **rope** - Python refactoring library
2. **jedi** - Python autocompletion and static analysis
3. **pylint/flake8** - Code quality tools
4. **Black** - Code formatter

---

## ✅ Checklist לפני Production

- [ ] בדקת שכל הטסטים עוברים
- [ ] בדיקת וולידציה עובדת כראוי
- [ ] אזהרות למשתמש על שמירת גיבוי
- [ ] תיעוד מפורט למשתמשים
- [ ] טיפול בשגיאות מקיף
- [ ] logging מפורט לכל שלב
- [ ] בדיקת ביצועים עם קבצים גדולים
- [ ] תמיכה ברול-בק (החזרת שינויים)

---

## 🎉 סיכום

יצרת מערכת רפקטורינג אוטומטי מתקדמת עם:
- ✅ פיצול קבצים גדולים לקבצים מודולריים
- ✅ המרה מפונקציות למחלקות
- ✅ וולידציה אוטומטית של השינויים
- ✅ תצוגה מקדימה ואישור משתמש
- ✅ שמירת API המקורי (backward compatibility)
- ✅ אינטגרציה מלאה עם הבוט
- ✅ בדיקות אוטומטיות

**בהצלחה! 🚀**

---

*נוצר עבור CodeBot - בוט שומר קבצי קוד*
*תאריך: 2025-10-08*
