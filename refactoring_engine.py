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
    # שיוך לפי סעיף (Section) אם זוהה מהקובץ המונוליתי
    section: Optional[str] = None


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
    # קוד המקור של המחלקה
    code: str = ""
    # שיוך לפי סעיף (Section) אם זוהה
    section: Optional[str] = None


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
        # מיפוי שורה -> slug של סעיף, לפי כותרות בקובץ
        self._sections_by_line: Dict[int, str] = {}

    def analyze(self) -> bool:
        """ניתוח הקוד"""
        try:
            self.tree = ast.parse(self.code)
            self._extract_sections()
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
                # שיוך לסעיף לפי מיקום השורה בקוד
                func_info.section = self._get_section_for_line(func_info.start_line)
                self.functions.append(func_info)

    def _extract_classes(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                class_info = self._parse_class(node)
                class_info.section = self._get_section_for_line(class_info.start_line)
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
        code_lines = self.code.splitlines()[node.lineno - 1 : node.end_lineno]
        code = "\n".join(code_lines)
        return ClassInfo(
            name=node.name,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            methods=methods,
            attributes=attributes,
            base_classes=base_classes,
            decorators=decorators,
            docstring=docstring,
            code=code,
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

    # --- זיהוי כותרות/סעיפים בקובץ (למשל "# 1) USER MANAGEMENT") ---
    def _extract_sections(self) -> None:
        """
        מאתר כותרות סעיפים בקובץ כדי לשמר קוהזיה סמנטית בפיצול.
        תומך בתבניות כגון:
        "# 1) USER MANAGEMENT"
        "# 2) PAYMENTS + SUBSCRIPTIONS"
        וכן וריאציות עם ריבוי תווי '#'.
        """
        self._sections_by_line = {}
        lines = self.code.splitlines()
        last_section: Optional[str] = None
        for idx, raw in enumerate(lines, start=1):
            line = raw.strip()
            # דלג על מפרידי "#####"
            if not line.startswith("#"):
                continue
            # הסר תווי '#'
            text = line.lstrip("#").strip()
            if not text:
                continue
            # נתמוך בתבנית "N) " בתחילת הקו אך לא נדרוש זאת
            m = re.match(r"^(\d+\)\s*)?(.+)$", text)
            if not m:
                continue
            title = m.group(2).strip()
            slug = self._section_to_slug(title)
            if slug:
                last_section = slug
                self._sections_by_line[idx] = slug

    def _section_to_slug(self, title: str) -> Optional[str]:
        t = title.lower()
        mapping = [
            (("user management", "users"), "users"),
            (("payments", "subscriptions", "billing", "finance"), "finance"),
            (("file system", "files", "storage"), "files"),
            (("inventory", "products"), "inventory"),
            (("network", "api clients", "api"), "api_clients"),
            (("analytics", "reports", "report"), "analytics"),
            (("notifications", "email"), "notifications"),
            (("permissions", "auth"), "permissions"),
            (("workflow", "pipelines"), "workflows"),
            (("debug", "temp", "mixed"), "debug"),
            (("random utilities", "utilities", "utils"), "utils"),
            (("application boot", "main"), "main"),
        ]
        for keys, slug in mapping:
            if any(k in t for k in keys):
                return slug
        return None

    def _get_section_for_line(self, line_no: int) -> Optional[str]:
        if not self._sections_by_line:
            return None
        keys = sorted(self._sections_by_line.keys())
        prev = None
        for k in keys:
            if k <= line_no:
                prev = k
            else:
                break
        return self._sections_by_line.get(prev) if prev is not None else None

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
        # הקצאת מחלקות לקבוצות (Collocation)
        classes_by_group = self._assign_classes_to_groups(groups)
        # בניית קבצי דומיין: מחלקות + פונקציות יחד
        for group_name, functions in groups.items():
            new_filename = f"{base_name}_{group_name}.py"
            group_classes = classes_by_group.get(group_name, [])
            # סינון imports לפי שימוש אמיתי בקוד המשולב
            combined_body_parts: List[str] = []
            for c in group_classes:
                combined_body_parts.append(c.code)
            for f in functions:
                combined_body_parts.append(f.code)
            group_code_body = "\n\n".join(combined_body_parts)
            filtered_imports = self._filter_imports_for_code(self.analyzer.imports, group_code_body)
            per_file_filtered_imports[new_filename] = filtered_imports
            file_content = self._build_file_content(functions, imports=filtered_imports, classes=group_classes)
            new_files[new_filename] = file_content
            changes.append(f"📦 {new_filename}: {len(group_classes)} מחלקות, {len(functions)} פונקציות")
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

        # אין יותר קובץ מחלקות מרכזי – מחלקות מרוכזות לפי דומיין (Collocation)

        # הזרקת יבוא לפונקציות בין-מודוליות (Cross-module function imports)
        func_to_module: Dict[str, str] = {}
        for group_name, functions in groups.items():
            module_stem = f"{base_name}_{group_name}"
            for f in functions:
                func_to_module[f.name] = module_stem
        new_files = self._inject_function_imports(new_files, func_to_module)
        # הזרקת יבוא למחלקות בין-מודוליות (Cross-module class imports)
        class_to_module: Dict[str, str] = {}
        for group_name, classes in classes_by_group.items():
            module_stem = f"{base_name}_{group_name}"
            for c in classes:
                class_to_module[c.name] = module_stem
        if class_to_module:
            new_files = self._inject_cross_module_class_imports(new_files, class_to_module)

        # ניקוי פוסט-פיצול: הסרת imports מיותרים ברמת קובץ
        new_files = self.post_refactor_cleanup(new_files)
        description = (
            f"🏗️ מצאתי {len(self.analyzer.classes)} מחלקות ו-{len(self.analyzer.functions)} פונקציות.\n\n"
            f"הצעת פיצול לפי דומיין (Collocation):\n"
            f"📦 {self.analyzer.filename} →\n"
        )
        for fname in new_files.keys():
            description += f"   ├── {fname}\n"
        description += "\n✅ מחלקות ופונקציות מרוכזות יחד בקבצי דומיין; אין קובץ מחלקות גנרי"
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
        קיבוץ פונקציות לפי קוהזיה סמנטית:
        1) סעיף (Section) אם זוהה מתוך כותרות הקובץ
        2) דומיין (IO/Compute/Helpers)
        3) Prefix ותלויות
        תוך שמירה על טווח קבוצות מועדף והימנעות מפיצול יתר.
        """
        if not self.analyzer:
            return {}
        functions = list(self.analyzer.functions)
        if len(functions) <= 1:
            return {"module": functions}
        if len(functions) == 2:
            return {
                f"group_{idx+1}_{func.name}": [func]
                for idx, func in enumerate(functions)
            }

        # 1) קיבוץ לפי סעיף (אם קיים). אם יש פונקציות ללא סעיף — נשמר אותן ע"י קיבוץ דומייני והוספה.
        section_groups = self._group_by_section(functions)
        if section_groups:
            leftovers = [f for f in functions if not f.section]
            if leftovers:
                domain_for_leftovers = self._group_by_domain(leftovers)
                for k, v in domain_for_leftovers.items():
                    section_groups.setdefault(k, []).extend(v)
        else:
            # אין כותרות כלל — קיבוץ דומייני מלא
            section_groups = self._group_by_domain(functions)

        # 2) קיבוץ נוסף לפי prefix בתוך כל דומיין, לשמירת קרבה סמנטית
        refined: Dict[str, List[FunctionInfo]] = {}
        for domain, funcs in section_groups.items():
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
            if len(sorted_groups) >= 2:
                # קח שתי קבוצות מובילות ואז מיזוג של יתר הקבוצות — לא זורקים פונקציות!
                refined = {
                    sorted_groups[0][0]: list(sorted_groups[0][1]),
                    sorted_groups[1][0]: list(sorted_groups[1][1]),
                }
                for name, funcs in sorted_groups[2:]:
                    # בחר יעד מיזוג לפי affinity אל אחת הקבוצות הקיימות
                    best_target = None
                    best_score = -1.0
                    for target_name, target_funcs in refined.items():
                        score = self._group_affinity(funcs, target_funcs)
                        if score > best_score:
                            best_score = score
                            best_target = target_name
                    if best_target is None:
                        # גיבוי: מזג לקבוצה הקטנה יותר כדי לאזן
                        best_target = min(refined.keys(), key=lambda k: len(refined[k]))
                    refined[best_target].extend(funcs)
            else:
                refined = {"module": functions}

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

    def _group_by_section(self, functions: List[FunctionInfo]) -> Dict[str, List[FunctionInfo]]:
        """קיבוץ פונקציות לפי סעיף (Section) אם קיים."""
        groups: Dict[str, List[FunctionInfo]] = {}
        for f in functions:
            if f.section:
                groups.setdefault(f.section, []).append(f)
        return groups

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

    def _merge_singletons_for_oop(self, groups: Dict[str, List[FunctionInfo]]) -> Dict[str, List[FunctionInfo]]:
        """
        ממזג קבוצות קטנות (פחות מ-min_functions_per_group) אל קבוצה דומה,
        כדי שלא יאבדו פונקציות כאשר מחלקות נוצרות רק עבור קבוצות עם 2+ פונקציות.
        """
        if len(groups) < 2:
            return groups
        # עבודה על העתק כדי לשנות בבטחה
        names = list(groups.keys())
        for name in names:
            funcs = groups.get(name, [])
            if len(funcs) >= self.min_functions_per_group:
                continue
            # מצא יעד מיזוג
            best_name = None
            best_score = -1.0
            for target_name, target_funcs in groups.items():
                if target_name == name:
                    continue
                score = self._group_affinity(funcs, target_funcs)
                if score > best_score:
                    best_score = score
                    best_name = target_name
            if best_name is None:
                # גיבוי: בחר את הקבוצה הגדולה ביותר
                best_name = max((k for k in groups.keys() if k != name), key=lambda k: len(groups[k]))
            groups[best_name].extend(funcs)
            if name in groups:
                del groups[name]
        return groups
    def _build_file_content(
        self,
        functions: List[FunctionInfo],
        imports: Optional[List[str]] = None,
        classes: Optional[List[ClassInfo]] = None,
    ) -> str:
        """בונה תוכן קובץ חדש עבור קבוצת דומיין עם מחלקות ופונקציות ובלוק imports מסונן."""
        content_parts: List[str] = []
        func_names = ", ".join(f.name for f in functions) if functions else ""
        class_names = ", ".join(c.name for c in (classes or [])) if classes else ""
        title_parts: List[str] = []
        if class_names:
            title_parts.append(f"מחלקות: {class_names}")
        if func_names:
            title_parts.append(f"פונקציות: {func_names}")
        title = " | ".join(title_parts) if title_parts else "מודול דומיין"
        content_parts.append(f'"""\n{title}\n"""\n')
        imports_list = list(imports or self.analyzer.imports)
        content_parts.extend(imports_list)
        content_parts.append("\n")
        # סדר: מחלקות תחילה, אחר כך פונקציות – מפחית צורך ב-import פנימי
        for cls in (classes or []):
            content_parts.append(cls.code)
            content_parts.append("\n\n")
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
        # מניעת איבוד פונקציות: מיזוג קבוצות קטנות (singleton) לפני בניית המחלקות
        if any(len(v) < self.min_functions_per_group for v in groups.values()) and len(groups) >= 2:
            groups = self._merge_singletons_for_oop(groups)
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

    # === תמיכה במחלקות: יצירת קובץ מחלקות והזרקת יבוא למחלקות בשימוש ===
    def _build_classes_file(self, base_name: str) -> Tuple[str, str]:
        """
        יוצר קובץ מרכזי לכל המחלקות שזוהו בקובץ המקורי.
        מחזיר (שם הקובץ, תוכן).
        """
        classes_stem = f"{base_name}_classes"
        filename = f"{classes_stem}.py"
        if not self.analyzer or not self.analyzer.classes:
            return filename, '"""\nמחלקות (אין)\n"""\n\n'
        # בעזרת מסנן imports, נשמור רק ייבוא שנדרש למחלקות
        classes_code_body = "\n\n".join(cls.code for cls in self.analyzer.classes)
        filtered_imports = self._filter_imports_for_code(self.analyzer.imports, classes_code_body)
        parts: List[str] = []
        parts.append('"""')
        parts.append("מחלקות שהופקו מהמונולית")
        parts.append('"""')
        parts.append("")
        parts.extend(filtered_imports)
        parts.append("")
        for cls in self.analyzer.classes:
            parts.append(cls.code)
            parts.append("")
        return filename, "\n".join(parts) + "\n"

    def _inject_class_imports(self, new_files: Dict[str, str], classes_filename: str) -> Dict[str, str]:
        """
        עבור כל מודול פונקציות, מזהה אילו מחלקות בשימוש ומזריק שורת import מתאימה.
        """
        classes_stem = Path(classes_filename).stem
        class_names = {cls.name for cls in (self.analyzer.classes if self.analyzer else [])}
        out: Dict[str, str] = {}
        for fn, content in new_files.items():
            if fn in ("__init__.py",) or fn == classes_filename or fn.endswith("_shared.py"):
                out[fn] = content
                continue
            used = self._extract_used_names(content)
            needed = sorted([name for name in class_names if name in used])
            if not needed:
                out[fn] = content
                continue
            lines = content.splitlines()
            # מצא את סוף הדוקסטרינג
            insert_idx = 0
            quote_count = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('"""'):
                    quote_count += 1
                    if quote_count == 2:
                        insert_idx = i + 2  # אחרי הדוקסטרינג ושורה ריקה
                        break
            import_line = f"from .{classes_stem} import {', '.join(needed)}"
            # הזרק אם לא קיים
            already = any(ln.strip().startswith(f"from .{classes_stem} import") for ln in lines)
            if not already:
                lines = lines[:insert_idx] + [import_line, ""] + lines[insert_idx:]
            out[fn] = "\n".join(lines) + "\n"
        return out

    def _extract_defined_functions_in_code(self, code: str) -> Set[str]:
        """שמות פונקציות טופ-לבל המוגדרות בקוד נתון."""
        defined: Set[str] = set()
        try:
            tree = ast.parse(code)
        except Exception:
            return defined
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # פונקציות טופ-לבל בלבד
                if not any(isinstance(parent, ast.ClassDef) and node in parent.body for parent in ast.walk(tree)):
                    defined.add(node.name)
        return defined

    def _inject_function_imports(self, new_files: Dict[str, str], func_to_module: Dict[str, str]) -> Dict[str, str]:
        """
        מזריק import יחסי לפונקציות שמוגדרות במודולים אחרים אך נמצאות בשימוש.
        """
        out: Dict[str, str] = {}
        for fn, content in new_files.items():
            if fn in ("__init__.py",) or fn.endswith("_shared.py"):
                out[fn] = content
                continue
            current_stem = Path(fn).stem
            used = self._extract_used_names(content)
            defined_here = self._extract_defined_functions_in_code(content)
            # פונקציות נדרשות: נמצאות בשימוש, ידוע היכן מוגדרות, לא מוגדרות כאן, ומוגדרות במודול אחר
            needed = [name for name in used if name in func_to_module and name not in defined_here and func_to_module[name] != current_stem]
            if not needed:
                out[fn] = content
                continue
            # קיבוץ לפי מודול יעד
            per_module: Dict[str, List[str]] = {}
            for name in needed:
                per_module.setdefault(func_to_module[name], []).append(name)
            lines = content.splitlines()
            # מצא את סוף הדוקסטרינג
            insert_idx = 0
            quote_count = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('"""'):
                    quote_count += 1
                    if quote_count == 2:
                        insert_idx = i + 2
                        break
            # בנה שורות import ללא כפילויות קיימות
            new_imports: List[str] = []
            for module_stem, names in per_module.items():
                names_sorted = sorted(set(names))
                imp = f"from .{module_stem} import {', '.join(names_sorted)}"
                exists = any(ln.strip().startswith(f"from .{module_stem} import") for ln in lines)
                if not exists:
                    new_imports.append(imp)
            if new_imports:
                lines = lines[:insert_idx] + new_imports + [""] + lines[insert_idx:]
            out[fn] = "\n".join(lines) + "\n"
        return out
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

    # === Collocation: הקצאת מחלקות לקבוצות פונקציות ובניית מיפוי ===
    def _extract_defined_classes_in_code(self, code: str) -> Set[str]:
        defined: Set[str] = set()
        try:
            tree = ast.parse(code)
        except Exception:
            return defined
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                defined.add(node.name)
        return defined

    def _assign_classes_to_groups(
        self, groups: Dict[str, List[FunctionInfo]]
    ) -> Dict[str, List[ClassInfo]]:
        """
        מקצה כל Class לקבוצת דומיין אחת לפי:
        - שימוש בפועל ע״י פונקציות הקבוצה (affinity)
        - התאמת Section (אם קיימת) לשם הקבוצה
        - דמיון שמות כאשר אין שימוש ברור
        """
        if not self.analyzer:
            return {}
        class_by_name: Dict[str, ClassInfo] = {c.name: c for c in self.analyzer.classes}
        groups_classes: Dict[str, List[ClassInfo]] = {g: [] for g in groups.keys()}
        if not class_by_name:
            return groups_classes

        # הכנה: שימושי קלאסים לפי פונקציות
        def used_names_in_function(func: FunctionInfo) -> Set[str]:
            return self._extract_used_names(func.code)

        # צבירת ניקוד שימוש לכל Class מול כל קבוצה
        score: Dict[Tuple[str, str], float] = {}  # (class_name, group_name) -> score
        for gname, funcs in groups.items():
            used_names: Set[str] = set()
            for f in funcs:
                used_names |= used_names_in_function(f)
            for cname in class_by_name.keys():
                s = 0.0
                if cname in used_names:
                    # נחשב שימוש ישיר במחלקה
                    s += 3.0
                # בונוס אם ה-Section של המחלקה תואם את שם הקבוצה
                cls_section = class_by_name[cname].section or ""
                if cls_section and cls_section == gname:
                    s += 2.0
                # דמיון לשם: כאשר אין שימוש או section
                if s == 0.0:
                    s += self._name_similarity(cname, gname)
                score[(cname, gname)] = s

        # התאמות לפי שימוש המחלקה בפונקציות (מתוך מתודות)
        # אם מתודות המחלקה קוראות לפונקציות בקבוצה ספציפית – נזיז לשם
        func_name_to_group: Dict[str, str] = {}
        for gname, funcs in groups.items():
            for f in funcs:
                func_name_to_group[f.name] = gname
        for cname, cls in class_by_name.items():
            group_bonus: Dict[str, float] = {}
            for m in cls.methods:
                for called in m.calls:
                    g = func_name_to_group.get(called)
                    if g:
                        group_bonus[g] = group_bonus.get(g, 0.0) + 1.0
            if group_bonus:
                # בונוס משמעותי לקבוצה עם מירב הקריאות
                best_g, best_v = max(group_bonus.items(), key=lambda kv: kv[1])
                score[(cname, best_g)] = score.get((cname, best_g), 0.0) + 3.0

        # הקצאה: בחר את הקבוצה עם הניקוד הגבוה ביותר לכל Class
        assigned_group_for_class: Dict[str, str] = {}
        for cname in class_by_name.keys():
            best_g = None
            best_s = float("-inf")
            for gname in groups.keys():
                s = score.get((cname, gname), 0.0)
                if s > best_s:
                    best_s = s
                    best_g = gname
            if best_g is None:
                # גיבוי: הצמד לקבוצה הראשונה
                best_g = next(iter(groups.keys()))
            assigned_group_for_class[cname] = best_g
            groups_classes[best_g].append(class_by_name[cname])

        return groups_classes

    def _inject_cross_module_class_imports(
        self,
        new_files: Dict[str, str],
        class_to_module: Dict[str, str],
    ) -> Dict[str, str]:
        """
        מזריק import יחסי למחלקות שמוגדרות במודולים אחרים אך נמצאות בשימוש.
        """
        out: Dict[str, str] = {}
        class_names: Set[str] = set(class_to_module.keys())
        for fn, content in new_files.items():
            if fn in ("__init__.py",) or fn.endswith("_shared.py"):
                out[fn] = content
                continue
            current_stem = Path(fn).stem
            used = self._extract_used_names(content)
            defined_here = self._extract_defined_classes_in_code(content)
            needed = [name for name in used if name in class_names and name not in defined_here and class_to_module.get(name) != current_stem]
            if not needed:
                out[fn] = content
                continue
            per_module: Dict[str, List[str]] = {}
            for name in needed:
                mod = class_to_module.get(name)
                if not mod:
                    continue
                per_module.setdefault(mod, []).append(name)
            lines = content.splitlines()
            # מצא את סוף הדוקסטרינג
            insert_idx = 0
            quote_count = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('"""'):
                    quote_count += 1
                    if quote_count == 2:
                        insert_idx = i + 2
                        break
            new_imports: List[str] = []
            for module_stem, names in per_module.items():
                names_sorted = sorted(set(names))
                imp = f"from .{module_stem} import {', '.join(names_sorted)}"
                exists = any(ln.strip().startswith(f"from .{module_stem} import") for ln in lines)
                if not exists:
                    new_imports.append(imp)
            if new_imports:
                lines = lines[:insert_idx] + new_imports + [""] + lines[insert_idx:]
            out[fn] = "\n".join(lines) + "\n"
        return out


# Instance גלובלי
refactoring_engine = RefactoringEngine()

