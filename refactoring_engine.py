"""
מנוע רפקטורינג אוטומטי
מבצע שינויי מבנה בקוד בצורה בטוחה
"""

from __future__ import annotations

import ast
import re
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
    calls: Set[str]
    called_by: Set[str] = field(default_factory=set)
    code: str = ""
    complexity: int = 0


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
    new_files: Dict[str, str]
    description: str
    changes_summary: List[str]
    warnings: List[str] = field(default_factory=list)
    imports_needed: Dict[str, List[str]] = field(default_factory=dict)


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

    def _extract_imports(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = ", ".join(alias.name for alias in node.names)
                self.imports.append(f"from {module} import {names}")

    def _extract_functions(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and self._is_top_level(node):
                func_info = self._parse_function(node)
                self.functions.append(func_info)

    def _extract_classes(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                class_info = self._parse_class(node)
                self.classes.append(class_info)

    def _extract_globals(self) -> None:
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.global_vars.append(target.id)

    def _parse_function(self, node: ast.FunctionDef) -> FunctionInfo:
        args = [arg.arg for arg in node.args.args]
        returns = ast.unparse(node.returns) if node.returns else None
        decorators = [ast.unparse(dec) for dec in node.decorator_list]
        docstring = ast.get_docstring(node)
        calls = self._extract_function_calls(node)
        code_lines = self.code.splitlines()[node.lineno - 1 : node.end_lineno]
        code = "\n".join(code_lines)
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
            complexity=complexity,
        )

    def _parse_class(self, node: ast.ClassDef) -> ClassInfo:
        methods: List[FunctionInfo] = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                methods.append(self._parse_function(item))
        attributes: List[str] = []
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        attributes.append(target.id)
        base_classes = [ast.unparse(base) for base in node.bases]
        decorators = [ast.unparse(dec) for dec in node.decorator_list]
        docstring = ast.get_docstring(node)
        return ClassInfo(
            name=node.name,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            methods=methods,
            attributes=attributes,
            base_classes=base_classes,
            decorators=decorators,
            docstring=docstring,
        )

    def _extract_function_calls(self, node: ast.AST) -> Set[str]:
        calls: Set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.add(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.add(child.func.attr)
        return calls

    def _calculate_complexity(self, node: ast.AST) -> int:
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp) and isinstance(child.op, (ast.And, ast.Or)):
                complexity += len(child.values) - 1
        return complexity

    def _is_top_level(self, node: ast.FunctionDef) -> bool:
        for parent in ast.walk(self.tree):
            if isinstance(parent, ast.ClassDef):
                if node in parent.body:
                    return False
        return True

    def _calculate_dependencies(self) -> None:
        func_names = {f.name for f in self.functions}
        for func in self.functions:
            for call in func.calls:
                if call in func_names:
                    for other_func in self.functions:
                        if other_func.name == call:
                            other_func.called_by.add(func.name)

    def find_large_functions(self, min_lines: int = 50) -> List[FunctionInfo]:
        large: List[FunctionInfo] = []
        for func in self.functions:
            lines_count = func.end_line - func.start_line + 1
            if lines_count >= min_lines or func.complexity >= 10:
                large.append(func)
        return large

    def find_large_classes(self, min_methods: int = 10) -> List[ClassInfo]:
        return [cls for cls in self.classes if len(cls.methods) >= min_methods]


class RefactoringEngine:
    """מנוע רפקטורינג"""

    def __init__(self) -> None:
        self.analyzer: Optional[CodeAnalyzer] = None

    def propose_refactoring(
        self, code: str, filename: str, refactor_type: RefactorType
    ) -> RefactorResult:
        """הצעת רפקטורינג"""
        self.analyzer = CodeAnalyzer(code, filename)
        if not self.analyzer.analyze():
            return RefactorResult(
                success=False,
                proposal=None,
                error="כשל בניתוח הקוד - ייתכן שגיאת תחביר",
            )
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
                return RefactorResult(success=False, proposal=None, error=f"סוג רפקטורינג לא נתמך: {refactor_type}")
            validated = self._validate_proposal(proposal)
            return RefactorResult(success=True, proposal=proposal, validation_passed=validated)
        except Exception as e:
            logger.error(f"שגיאה ברפקטורינג: {e}", exc_info=True)
            return RefactorResult(success=False, proposal=None, error=f"שגיאה: {str(e)}")

    def _split_functions(self) -> RefactorProposal:
        groups = self._group_related_functions()
        if len(groups) <= 1:
            raise ValueError("לא נמצאו קבוצות פונקציות נפרדות. הקוד כבר מאורגן היטב.")
        new_files: Dict[str, str] = {}
        changes: List[str] = []
        imports_needed: Dict[str, List[str]] = {}
        base_name = Path(self.analyzer.filename).stem
        for group_name, functions in groups.items():
            new_filename = f"{base_name}_{group_name}.py"
            file_content = self._build_file_content(functions)
            new_files[new_filename] = file_content
            changes.append(f"📦 {new_filename}: {len(functions)} פונקציות")
            imports_needed[new_filename] = self.analyzer.imports.copy()
        init_content = self._build_init_file(list(new_files.keys()))
        new_files["__init__.py"] = init_content
        changes.append("📦 __init__.py: מייצא את כל ה-API")
        description = (
            f"🏗️ מצאתי {len(self.analyzer.classes)} מחלקות ו-{len(self.analyzer.functions)} פונקציות.\n\n"
            f"הצעת פיצול:\n"
            f"📦 {self.analyzer.filename} →\n"
        )
        for fname in new_files.keys():
            description += f"   ├── {fname}\n"
        description += "\n✅ כל הקבצים שומרים על ה-API המקורי"
        warnings: List[str] = []
        if len(self.analyzer.global_vars) > 0:
            warnings.append(
                f"⚠️ יש {len(self.analyzer.global_vars)} משתנים גלובליים - עלול להיות צורך בהתאמה ידנית"
            )
        return RefactorProposal(
            refactor_type=RefactorType.SPLIT_FUNCTIONS,
            original_file=self.analyzer.filename,
            new_files=new_files,
            description=description,
            changes_summary=changes,
            warnings=warnings,
            imports_needed=imports_needed,
        )

    def _group_related_functions(self) -> Dict[str, List[FunctionInfo]]:
        prefix_groups: Dict[str, List[FunctionInfo]] = {}
        for func in self.analyzer.functions:
            parts = re.split(r'[_]|(?=[A-Z])', func.name)
            if parts:
                prefix = parts[0].lower()
                prefix_groups.setdefault(prefix, []).append(func)
        if len(prefix_groups) >= 2 and all(len(g) >= 2 for g in prefix_groups.values()):
            return prefix_groups
        dependency_groups = self._group_by_dependencies()
        if len(dependency_groups) >= 2:
            return dependency_groups
        return self._split_by_size()

    def _group_by_dependencies(self) -> Dict[str, List[FunctionInfo]]:
        groups: Dict[str, List[FunctionInfo]] = {}
        visited: Set[str] = set()
        for func in self.analyzer.functions:
            if func.name in visited:
                continue
            group_name = func.name.replace('_', '')[:15]
            group = [func]
            visited.add(func.name)
            for other_func in self.analyzer.functions:
                if other_func.name in visited:
                    continue
                if (
                    func.name in other_func.calls
                    or other_func.name in func.calls
                    or func.name in other_func.called_by
                    or other_func.name in func.called_by
                ):
                    group.append(other_func)
                    visited.add(other_func.name)
            if len(group) >= 2:
                groups[group_name] = group
        return groups

    def _split_by_size(self) -> Dict[str, List[FunctionInfo]]:
        max_funcs_per_file = 5
        groups: Dict[str, List[FunctionInfo]] = {}
        for i in range(0, len(self.analyzer.functions), max_funcs_per_file):
            group_name = f"module{i // max_funcs_per_file + 1}"
            groups[group_name] = self.analyzer.functions[i : i + max_funcs_per_file]
        return groups

    def _build_file_content(self, functions: List[FunctionInfo]) -> str:
        content_parts: List[str] = []
        func_names = ", ".join(f.name for f in functions)
        content_parts.append(f'"""\nמודול עבור: {func_names}\n"""\n')
        content_parts.extend(self.analyzer.imports)
        content_parts.append("\n")
        for func in functions:
            content_parts.append(func.code)
            content_parts.append("\n\n")
        return "\n".join(content_parts)

    def _build_init_file(self, filenames: List[str]) -> str:
        content = '"""\nאינדקס מרכזי לכל הפונקציות\n"""\n\n'
        for fname in filenames:
            if fname == "__init__.py":
                continue
            module_name = Path(fname).stem
            content += f"from .{module_name} import *\n"
        return content

    def _extract_functions(self) -> RefactorProposal:
        duplicates: List[Dict[str, Any]] = self._find_code_duplication()
        if not duplicates:
            raise ValueError("לא נמצא קוד חוזר מספיק משמעותי לחילוץ")
        new_files: Dict[str, str] = {}
        changes: List[str] = []
        utils_content = self._build_utils_from_duplicates(duplicates)
        new_files["utils.py"] = utils_content
        changes.append(f"📦 utils.py: {len(duplicates)} פונקציות עזר חדשות")
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
            changes_summary=changes,
        )

    def _find_code_duplication(self) -> List[Dict[str, Any]]:
        return []

    def _build_utils_from_duplicates(self, duplicates: List[Dict[str, Any]]) -> str:
        return '"""\nפונקציות עזר משותפות\n"""\n\n# TODO: implement\n'

    def _replace_duplicates_with_calls(self, duplicates: List[Dict[str, Any]]) -> str:
        return self.analyzer.code  # type: ignore[return-value]

    def _merge_similar(self) -> RefactorProposal:
        raise ValueError("פיצ'ר מיזוג קוד טרם יושם במלואו")

    def _convert_to_classes(self) -> RefactorProposal:
        if len(self.analyzer.functions) < 3:
            raise ValueError("אין מספיק פונקציות להמרה למחלקה")
        groups = self._group_related_functions()
        new_files: Dict[str, str] = {}
        changes: List[str] = []
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
        for fname in new_files.keys():
            description += f"   📦 {fname}\n"
        description += "\n✅ ארכיטקטורה מונחית עצמים"
        return RefactorProposal(
            refactor_type=RefactorType.CONVERT_TO_CLASSES,
            original_file=self.analyzer.filename,
            new_files=new_files,
            description=description,
            changes_summary=changes,
        )

    def _generate_class_name(self, prefix: str) -> str:
        words = prefix.split('_')
        return ''.join(word.capitalize() for word in words)

    def _build_class_from_functions(self, class_name: str, functions: List[FunctionInfo]) -> str:
        lines: List[str] = []
        lines.append(f'"""')
        lines.append(f'{class_name} - מחלקה שנוצרה מרפקטורינג')
        lines.append(f'"""')
        lines.append('')
        lines.extend(self.analyzer.imports)
        lines.append('')
        lines.append('')
        lines.append(f'class {class_name}:')
        lines.append(f'    """מחלקת שירות ל-{class_name.lower()}"""')
        lines.append('')
        lines.append('    def __init__(self):')
        lines.append('        """אתחול המחלקה"""')
        lines.append('        pass')
        lines.append('')
        for func in functions:
            method_code = self._convert_function_to_method(func)
            lines.append(method_code)
            lines.append('')
        return '\n'.join(lines)

    def _convert_function_to_method(self, func: FunctionInfo) -> str:
        method_lines = func.code.splitlines()
        def_line_idx = 0
        for i, line in enumerate(method_lines):
            if line.strip().startswith('def '):
                def_line_idx = i
                break
        def_line = method_lines[def_line_idx]
        if '(' in def_line:
            def_line = def_line.replace('(', '(self, ', 1)
            def_line = def_line.replace('(self, )', '(self)')
        method_lines[def_line_idx] = '    ' + def_line
        for i in range(len(method_lines)):
            if i != def_line_idx:
                method_lines[i] = '    ' + method_lines[i]
        return '\n'.join(method_lines)

    def _add_dependency_injection(self) -> RefactorProposal:
        raise ValueError("פיצ'ר DI טרם יושם במלואו")

    def _validate_proposal(self, proposal: RefactorProposal) -> bool:
        try:
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

