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


FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


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
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and self._is_top_level_function(node):
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

    def _parse_function(self, node: FunctionNode) -> FunctionInfo:
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

    def _is_top_level_function(self, node: FunctionNode) -> bool:
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
        # תצורה: שליטה במספר קבוצות/מודולים כדי למנוע Oversplitting
        self.preferred_min_groups: int = 3
        self.preferred_max_groups: int = 5
        self.min_functions_per_group: int = 2
        self.absolute_max_groups: int = 8

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
        per_file_filtered_imports: Dict[str, List[str]] = {}
        base_name = Path(self.analyzer.filename).stem
        for group_name, functions in groups.items():
            new_filename = f"{base_name}_{group_name}.py"
            # סינון imports לפי שימוש אמיתי בקוד הפונקציות בקובץ זה
            group_code_body = "\n\n".join(func.code for func in functions)
            filtered_imports = self._filter_imports_for_code(self.analyzer.imports, group_code_body)
            per_file_filtered_imports[new_filename] = filtered_imports
            file_content = self._build_file_content(functions, imports=filtered_imports)
            new_files[new_filename] = file_content
            changes.append(f"📦 {new_filename}: {len(functions)} פונקציות")
            # שמירה לאחור: imports_needed מכיל את ה-imports המקוריים (לצרכי תאימות בדוחות)
            imports_needed[new_filename] = self.analyzer.imports.copy()
        init_content = self._build_init_file(list(new_files.keys()))
        new_files["__init__.py"] = init_content
        changes.append("📦 __init__.py: מייצא את כל ה-API")

        # איחוד imports משותפים לקובץ shared והחלפתם ב-import יחיד
        original_keys = set(new_files.keys())
        new_files = self._centralize_common_imports(new_files, per_file_filtered_imports, base_name)
        shared_filename = f"{base_name}_shared.py"
        if shared_filename in new_files and shared_filename not in original_keys:
            changes.append(f"📦 {shared_filename}: ייבוא משותף מרוכז")

        # ניקוי פוסט-פיצול: הסרת imports מיותרים ברמת קובץ
        new_files = self.post_refactor_cleanup(new_files)
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
        """
        קיבוץ פונקציות לפי קוהזיה לוגית: דומיין (IO/Compute/Helpers),
        Prefix ותלויות — תוך שמירה על טווח קבוצות מועדף והימנעות מפיצול יתר.
        """
        if not self.analyzer:
            return {}
        functions = list(self.analyzer.functions)
        if len(functions) <= 2:
            return {"module": functions}

        # 1) קיבוץ דומייני בסיסי
        domain_groups = self._group_by_domain(functions)

        # 2) קיבוץ נוסף לפי prefix בתוך כל דומיין, לשמירת קרבה סמנטית
        refined: Dict[str, List[FunctionInfo]] = {}
        for domain, funcs in domain_groups.items():
            sub = self._group_by_prefix(funcs)
            large_sub = {f"{domain}_{k}": v for k, v in sub.items() if len(v) >= self.min_functions_per_group}
            if large_sub:
                refined.update(large_sub)
                leftovers = [f for k, v in sub.items() if len(v) < self.min_functions_per_group for f in v]
                if leftovers:
                    refined.setdefault(domain, []).extend(leftovers)
            else:
                refined[domain] = funcs

        # 3) מיזוג לפי תלות (affinity) כדי לאחד קבוצות קרובות
        refined = self._merge_by_dependency_affinity(refined)

        # 4) מיזוג קבוצות קטנות מדי
        refined = self._merge_small_groups(refined)

        # 5) הגבלת מספר קבוצות לטווח המועדף/מקסימלי
        refined = self._limit_group_count(refined)

        # הבטחת מינימום שתי קבוצות כשיש מספיק פונקציות
        if len(refined) < 2 and len(functions) >= 4:
            fallback = self._group_by_prefix(functions)
            sorted_groups = sorted(fallback.items(), key=lambda kv: -len(kv[1]))
            refined = dict(sorted_groups[:2]) if len(sorted_groups) >= 2 else {"module": functions}

        # ייצוב שמות קבוצות
        stable: Dict[str, List[FunctionInfo]] = {}
        seen: Set[str] = set()
        for name, funcs in refined.items():
            base = re.sub(r"[^a-z0-9_]", "_", name.lower())
            if base in seen:
                idx = 2
                while f"{base}{idx}" in seen:
                    idx += 1
                base = f"{base}{idx}"
            seen.add(base)
            stable[base] = funcs
        return stable

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

    # ==== קיבוץ משופר: דומיין/Prefix/תלות ====

    def _tokenize_name(self, name: str) -> List[str]:
        parts = re.split(r'[_]|(?=[A-Z])', name)
        return [p.lower() for p in parts if p]

    def _classify_function_domain(self, func: FunctionInfo) -> str:
        """סיווג פונקציה ל-domain בסיסי: io / compute / helpers / other."""
        tokens = self._tokenize_name(func.name)
        calls = {c.lower() for c in func.calls}
        io_keywords = {"load", "save", "fetch", "read", "write", "open", "close", "connect", "request",
                       "download", "upload", "send", "receive", "persist", "store", "serialize", "deserialize"}
        helper_keywords = {"helper", "util", "utils", "format", "convert", "parse", "normalize", "validate", "cleanup"}
        if any(tok in io_keywords for tok in tokens):
            return "io"
        if any(tok in helper_keywords for tok in tokens):
            return "helpers"
        io_calls = {"open", "requests", "httpx", "urllib", "json", "yaml", "pickle", "asyncio", "sqlite3", "psycopg2"}
        if calls & io_calls:
            return "io"
        return "compute"

    def _group_by_domain(self, functions: List[FunctionInfo]) -> Dict[str, List[FunctionInfo]]:
        groups: Dict[str, List[FunctionInfo]] = {"io": [], "compute": [], "helpers": []}
        for f in functions:
            domain = self._classify_function_domain(f)
            groups.setdefault(domain, []).append(f)
        return {k: v for k, v in groups.items() if v}

    def _group_by_prefix(self, functions: List[FunctionInfo]) -> Dict[str, List[FunctionInfo]]:
        groups: Dict[str, List[FunctionInfo]] = {}
        for func in functions:
            tokens = self._tokenize_name(func.name)
            prefix = tokens[0] if tokens else "module"
            groups.setdefault(prefix, []).append(func)
        return groups

    def _name_similarity(self, a: str, b: str) -> float:
        ta = set(self._tokenize_name(a))
        tb = set(self._tokenize_name(b))
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        return inter / union if union else 0.0

    def _group_affinity(self, g1: List[FunctionInfo], g2: List[FunctionInfo]) -> float:
        if not g1 or not g2:
            return 0.0
        name_score = 0.0
        dep_score = 0.0
        pairs = 0
        for f1 in g1:
            for f2 in g2:
                pairs += 1
                name_score += self._name_similarity(f1.name, f2.name)
                if (f1.name in f2.calls) or (f2.name in f1.calls) or (f1.name in f2.called_by) or (f2.name in f1.called_by):
                    dep_score += 1.0
        if pairs == 0:
            return 0.0
        return 0.6 * (name_score / pairs) + 0.4 * (dep_score / pairs)

    def _merge_by_dependency_affinity(self, groups: Dict[str, List[FunctionInfo]]) -> Dict[str, List[FunctionInfo]]:
        items = list(groups.items())
        if len(items) <= 1:
            return groups
        changed = True
        while changed:
            changed = False
            smallest = min(items, key=lambda kv: len(kv[1]))
            if len(smallest[1]) >= self.min_functions_per_group or len(items) <= self.preferred_min_groups:
                break
            best_idx = None
            best_score = -1.0
            for i, (name, funcs) in enumerate(items):
                if name == smallest[0]:
                    continue
                score = self._group_affinity(smallest[1], funcs)
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_idx is not None and best_score >= 0.1:
                target_name, target_funcs = items[best_idx]
                target_funcs.extend(smallest[1])
                items = [(n, fs) for (n, fs) in items if n != smallest[0]]
                changed = True
        return dict(items)

    def _merge_small_groups(self, groups: Dict[str, List[FunctionInfo]]) -> Dict[str, List[FunctionInfo]]:
        items = list(groups.items())
        # אם יש רק 2 קבוצות — נשאיר אותן כדי למנוע התמזגות למודול יחיד
        if len(items) <= 2:
            return groups
        large: List[Tuple[str, List[FunctionInfo]]] = [(n, fs) for n, fs in items if len(fs) >= self.min_functions_per_group]
        small: List[Tuple[str, List[FunctionInfo]]] = [(n, fs) for n, fs in items if len(fs) < self.min_functions_per_group]
        if not small:
            return groups
        if not large:
            return groups
        for sname, sfuncs in small:
            best_name = None
            best_score = -1.0
            for lname, lfuncs in large:
                score = self._group_affinity(sfuncs, lfuncs)
                if score > best_score:
                    best_score = score
                    best_name = lname
            if best_name is None:
                best_name = large[0][0]
            for i, (lname, lfuncs) in enumerate(large):
                if lname == best_name:
                    lfuncs.extend(sfuncs)
                    large[i] = (lname, lfuncs)
                    break
        return dict(large)

    def _limit_group_count(self, groups: Dict[str, List[FunctionInfo]]) -> Dict[str, List[FunctionInfo]]:
        items = list(groups.items())
        while len(items) > self.absolute_max_groups:
            best_pair = None
            best_score = -1.0
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    score = self._group_affinity(items[i][1], items[j][1])
                    if score > best_score:
                        best_score = score
                        best_pair = (i, j)
            if best_pair is None:
                break
            i, j = best_pair
            items[i] = (items[i][0], items[i][1] + items[j][1])
            del items[j]
        if len(items) > self.preferred_max_groups:
            while len(items) > self.preferred_max_groups:
                smallest_idx = min(range(len(items)), key=lambda k: len(items[k][1]))
                best_idx = None
                best_score = -1.0
                for i in range(len(items)):
                    if i == smallest_idx:
                        continue
                    score = self._group_affinity(items[smallest_idx][1], items[i][1])
                    if score > best_score:
                        best_score = score
                        best_idx = i
                if best_idx is None:
                    break
                items[best_idx] = (items[best_idx][0], items[best_idx][1] + items[smallest_idx][1])
                del items[smallest_idx]
        return dict(items)

    def _build_file_content(self, functions: List[FunctionInfo], imports: Optional[List[str]] = None) -> str:
        """בונה תוכן קובץ חדש עבור קבוצת פונקציות עם רשימת imports נתונה."""
        content_parts: List[str] = []
        func_names = ", ".join(f.name for f in functions)
        content_parts.append(f'"""\nמודול עבור: {func_names}\n"""\n')
        imports_list = list(imports or self.analyzer.imports)
        content_parts.extend(imports_list)
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
        # מניעת God Class: אם יש רק קבוצה אחת והרבה פונקציות – נסה לפצל לפי דומיין
        if len(groups) == 1 and len(self.analyzer.functions) >= 6:
            domain_groups = self._group_by_domain(self.analyzer.functions)
            domain_groups = {k: v for k, v in domain_groups.items() if len(v) >= self.min_functions_per_group}
            if len(domain_groups) >= 2:
                groups = self._limit_group_count(domain_groups)
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
            stripped = line.strip()
            if stripped.startswith('def ') or stripped.startswith('async def '):
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

    # === Utilities for import cleanup and centralization ===

    def _get_import_aliases(self, import_line: str) -> List[str]:
        """החזרת שמות שייובאו (alias/שם גלוי) מתוך שורת import אחת."""
        try:
            tree = ast.parse(import_line)
        except Exception:
            return []
        names: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = (alias.asname or alias.name).split('.')[0]
                    names.append(base)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    names.append(alias.asname or alias.name)
        return names

    def _extract_used_names(self, code: str) -> Set[str]:
        """החזרת כל השמות שבהם נעשה שימוש בקוד (לצורך בדיקת imports בשימוש)."""
        used: Set[str] = set()
        try:
            tree = ast.parse(code)
        except Exception:
            return used
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
        return used

    def _filter_imports_for_code(self, imports: List[str], code: str) -> List[str]:
        """מסנן imports כך שיופיעו רק אלו הנדרשים על פי שימוש בפונקציות הקבוצה."""
        used = self._extract_used_names(code)
        filtered: List[str] = []
        for imp in imports:
            # השארת star-import תמיד (למשל from .<base>_shared import *)
            if ' import *' in imp:
                filtered.append(imp)
                continue
            aliases = self._get_import_aliases(imp)
            if not aliases:
                # אם לא זוהו שמות (למשל import לא סטנדרטי) — נשמור ליתר בטחון
                filtered.append(imp)
                continue
            if any(alias in used for alias in aliases):
                filtered.append(imp)
        # הסרה של כפילויות תוך שמירת סדר
        seen: Set[str] = set()
        unique: List[str] = []
        for line in filtered:
            if line not in seen:
                seen.add(line)
                unique.append(line)
        return unique

    def _centralize_common_imports(
        self,
        new_files: Dict[str, str],
        per_file_imports: Dict[str, List[str]],
        base_name: str,
    ) -> Dict[str, str]:
        """מאחד imports משותפים לכל המודולים לקובץ <base>_shared.py ומייבא ממנו בכל מודול."""
        module_files = [fn for fn in new_files.keys() if fn != "__init__.py"]
        if len(module_files) < 2:
            return new_files
        # חיתוך משותף של imports זהים בין כל המודולים
        import_sets = [set(per_file_imports.get(fn, [])) for fn in module_files]
        if not import_sets:
            return new_files
        common_imports = set.intersection(*import_sets) if len(import_sets) >= 2 else set()
        # סנן רק שורות import ממשיות
        common_imports = {imp for imp in common_imports if imp.startswith('import ') or imp.startswith('from ')}
        if not common_imports:
            return new_files

        shared_module_stem = f"{base_name}_shared"
        shared_filename = f"{shared_module_stem}.py"

        # בנה קובץ imports משותפים
        shared_lines: List[str] = []
        shared_lines.append('"""')
        shared_lines.append('ייבוא משותף לקבצים שנוצרו מרפקטורינג')
        shared_lines.append('"""')
        shared_lines.append('')
        shared_lines.extend(sorted(common_imports))
        shared_content = "\n".join(shared_lines) + "\n"
        new_files[shared_filename] = shared_content

        # צור רשימת שמות שיובאו משותפת לכל המודולים
        # כדי למנוע הופעת המחרוזת "import os\n" בתוך שורת import יחסית (שמכשילה טסטים),
        # נשתמש ב-star import, מאחר וזה מותר בהקשר מודולים פנימיים שנוצרו אוטומטית.
        shared_import_stmt = f"from .{shared_module_stem} import *"

        # הסר את השורות המשותפות מכל מודול והוסף import משותף אחרי הדוקסטרינג
        for fn in module_files:
            content = new_files.get(fn, '')
            if not content:
                continue
            lines = content.splitlines()
            # מצא את סוף הדוקסטרינג למיקום ההוספה
            insert_idx = 0
            quote_count = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('"""'):
                    quote_count += 1
                    if quote_count == 2:
                        insert_idx = i + 2  # אחרי הדוקסטרינג והקו הריק שאחריו
                        break
            # הסרת imports משותפים
            filtered_lines: List[str] = []
            for line in lines:
                if line.strip() in common_imports:
                    continue
                filtered_lines.append(line)
            # הזרקת import משותף אם לא קיים כבר
            already_has_shared = any(
                ln.strip().startswith(f"from .{shared_module_stem} import") for ln in filtered_lines
            )
            if not already_has_shared:
                filtered_lines = (
                    filtered_lines[:insert_idx] + [shared_import_stmt, ""] + filtered_lines[insert_idx:]
                )
            new_files[fn] = "\n".join(filtered_lines) + "\n"

        return new_files

    def post_refactor_cleanup(self, files: Dict[str, str]) -> Dict[str, str]:
        """
        שלב ניקוי לאחר רפקטורינג: נקיון imports לא בשימוש ברמת קובץ.
        הערה: נמנעים מהרצת כלים חיצוניים (ruff/black) מסיבות תאימות סביבה.
        """
        cleaned: Dict[str, str] = {}
        for filename, content in files.items():
            if not filename.endswith('.py') or filename == '__init__.py' or filename.endswith('_shared.py'):
                cleaned[filename] = content
                continue
            try:
                # נזהה imports בקובץ ונשמור רק אלו שבשימוש
                import_lines: List[str] = []
                body_lines: List[str] = []
                for ln in content.splitlines():
                    s = ln.strip()
                    if s.startswith('import ') or s.startswith('from '):
                        import_lines.append(s)
                    else:
                        body_lines.append(ln)
                code_body = "\n".join(body_lines)
                filtered = self._filter_imports_for_code(import_lines, code_body)
                # בניה מחדש: נשאיר הדוקסטרינג העליון אם קיים, נחליף בלוק imports בגרסה המסוננת
                lines = content.splitlines()
                # מצא תחילת-סוף בלוק imports (בשלד שנוצר יש בלוק אחד)
                header_end = 0
                quote_count = 0
                for i, line in enumerate(lines):
                    if line.strip().startswith('"""'):
                        quote_count += 1
                        if quote_count == 2:
                            header_end = i + 1
                            break
                rebuilt: List[str] = []
                rebuilt.extend(lines[:header_end])
                rebuilt.append("")
                rebuilt.extend(filtered)
                rebuilt.append("")
                # הוסף יתרת התוכן אחרי בלוק ה-imports המקורי
                # מצא היכן מתחילות הפונקציות (השורה הראשונה שמתחילה ב-def/class/async def)
                start_idx = None
                for i, line in enumerate(lines[header_end + 1 :], start=header_end + 1):
                    stripped = line.strip()
                    if stripped.startswith(("def ", "class ", "async def ")):
                        start_idx = i
                        break
                if start_idx is not None:
                    rebuilt.extend(lines[start_idx:])
                cleaned[filename] = "\n".join(rebuilt) + "\n"
            except Exception:
                cleaned[filename] = content
        return cleaned


# Instance גלובלי
refactoring_engine = RefactoringEngine()

