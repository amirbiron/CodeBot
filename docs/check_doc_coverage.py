#!/usr/bin/env python3
"""
בדיקת כיסוי תיעוד - Code Keeper Bot
=====================================

סקריפט לבדיקת אחוז הפונקציות והמחלקות המתועדות בפרויקט.
"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def has_docstring(node) -> bool:
    """בודק אם לצומת AST יש docstring."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (
            node.body and
            isinstance(node.body[0], ast.Expr) and
            isinstance(node.body[0].value, ast.Constant) and
            isinstance(node.body[0].value.value, str)
        )
    return False

def analyze_file(filepath: Path) -> Dict[str, List[str]]:
    """
    מנתח קובץ Python ומחזיר מידע על תיעוד.
    
    Args:
        filepath: נתיב לקובץ Python
    
    Returns:
        מילון עם רשימות של פריטים מתועדים ולא מתועדים
    """
    results = {
        'documented_functions': [],
        'undocumented_functions': [],
        'documented_classes': [],
        'undocumented_classes': [],
        'documented_methods': [],
        'undocumented_methods': [],
    }
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
    except (SyntaxError, UnicodeDecodeError):
        return results
    
    for node in ast.walk(tree):
        # Check functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private functions (start with _)
            if node.name.startswith('_') and not node.name.startswith('__'):
                continue
                
            # Check if it's a method (inside a class)
            is_method = any(isinstance(parent, ast.ClassDef) 
                          for parent in ast.walk(tree) 
                          if node in ast.walk(parent))
            
            if has_docstring(node):
                if is_method:
                    results['documented_methods'].append(node.name)
                else:
                    results['documented_functions'].append(node.name)
            else:
                if is_method:
                    results['undocumented_methods'].append(node.name)
                else:
                    results['undocumented_functions'].append(node.name)
        
        # Check classes
        elif isinstance(node, ast.ClassDef):
            if has_docstring(node):
                results['documented_classes'].append(node.name)
            else:
                results['undocumented_classes'].append(node.name)
    
    return results

def analyze_project(root_dir: Path, exclude_dirs: List[str] = None) -> Dict:
    """
    מנתח את כל הפרויקט ומחזיר סטטיסטיקות תיעוד.
    
    Args:
        root_dir: תיקיית השורש של הפרויקט
        exclude_dirs: רשימת תיקיות להתעלם מהן
    
    Returns:
        מילון עם סטטיסטיקות תיעוד
    """
    if exclude_dirs is None:
        exclude_dirs = [
            '__pycache__', '.git', '.venv', 'venv', 
            'env', 'build', 'dist', '.tox', 'docs',
            'tests', 'test', '.pytest_cache'
        ]
    
    all_results = defaultdict(list)
    file_count = 0
    
    for py_file in root_dir.rglob('*.py'):
        # Skip excluded directories
        if any(excluded in py_file.parts for excluded in exclude_dirs):
            continue
        
        # Skip __pycache__ and test files
        if '__pycache__' in str(py_file) or 'test_' in py_file.name:
            continue
        
        file_results = analyze_file(py_file)
        file_count += 1
        
        for key, values in file_results.items():
            all_results[key].extend(values)
    
    # Calculate statistics
    stats = {
        'files_analyzed': file_count,
        'total_functions': len(all_results['documented_functions']) + len(all_results['undocumented_functions']),
        'documented_functions': len(all_results['documented_functions']),
        'undocumented_functions': len(all_results['undocumented_functions']),
        'total_classes': len(all_results['documented_classes']) + len(all_results['undocumented_classes']),
        'documented_classes': len(all_results['documented_classes']),
        'undocumented_classes': len(all_results['undocumented_classes']),
        'total_methods': len(all_results['documented_methods']) + len(all_results['undocumented_methods']),
        'documented_methods': len(all_results['documented_methods']),
        'undocumented_methods': len(all_results['undocumented_methods']),
        'undocumented_items': all_results['undocumented_functions'] + 
                              all_results['undocumented_classes'] + 
                              all_results['undocumented_methods']
    }
    
    # Calculate percentages
    if stats['total_functions'] > 0:
        stats['function_coverage'] = (stats['documented_functions'] / stats['total_functions']) * 100
    else:
        stats['function_coverage'] = 100
    
    if stats['total_classes'] > 0:
        stats['class_coverage'] = (stats['documented_classes'] / stats['total_classes']) * 100
    else:
        stats['class_coverage'] = 100
    
    if stats['total_methods'] > 0:
        stats['method_coverage'] = (stats['documented_methods'] / stats['total_methods']) * 100
    else:
        stats['method_coverage'] = 100
    
    total_items = stats['total_functions'] + stats['total_classes'] + stats['total_methods']
    documented_items = stats['documented_functions'] + stats['documented_classes'] + stats['documented_methods']
    
    if total_items > 0:
        stats['overall_coverage'] = (documented_items / total_items) * 100
    else:
        stats['overall_coverage'] = 100
    
    return stats

def print_report(stats: Dict, verbose: bool = False):
    """
    מדפיס דוח כיסוי תיעוד.
    
    Args:
        stats: סטטיסטיקות התיעוד
        verbose: האם להציג פרטים מלאים
    """
    print(f"\n{Colors.BOLD}📖 Documentation Coverage Report{Colors.END}")
    print("=" * 50)
    
    print(f"\n📁 Files analyzed: {stats['files_analyzed']}")
    
    # Functions
    print(f"\n{Colors.BOLD}Functions:{Colors.END}")
    coverage = stats['function_coverage']
    color = Colors.GREEN if coverage >= 80 else Colors.YELLOW if coverage >= 60 else Colors.RED
    print(f"  Total: {stats['total_functions']}")
    print(f"  Documented: {stats['documented_functions']}")
    print(f"  Undocumented: {stats['undocumented_functions']}")
    print(f"  Coverage: {color}{coverage:.1f}%{Colors.END}")
    
    # Classes
    print(f"\n{Colors.BOLD}Classes:{Colors.END}")
    coverage = stats['class_coverage']
    color = Colors.GREEN if coverage >= 80 else Colors.YELLOW if coverage >= 60 else Colors.RED
    print(f"  Total: {stats['total_classes']}")
    print(f"  Documented: {stats['documented_classes']}")
    print(f"  Undocumented: {stats['undocumented_classes']}")
    print(f"  Coverage: {color}{coverage:.1f}%{Colors.END}")
    
    # Methods
    print(f"\n{Colors.BOLD}Methods:{Colors.END}")
    coverage = stats['method_coverage']
    color = Colors.GREEN if coverage >= 80 else Colors.YELLOW if coverage >= 60 else Colors.RED
    print(f"  Total: {stats['total_methods']}")
    print(f"  Documented: {stats['documented_methods']}")
    print(f"  Undocumented: {stats['undocumented_methods']}")
    print(f"  Coverage: {color}{coverage:.1f}%{Colors.END}")
    
    # Overall
    print(f"\n{Colors.BOLD}Overall Coverage:{Colors.END}")
    coverage = stats['overall_coverage']
    color = Colors.GREEN if coverage >= 80 else Colors.YELLOW if coverage >= 60 else Colors.RED
    print(f"  {color}{coverage:.1f}%{Colors.END}")
    
    # Grade
    if coverage >= 90:
        grade = "A"
        emoji = "🌟"
    elif coverage >= 80:
        grade = "B"
        emoji = "✅"
    elif coverage >= 70:
        grade = "C"
        emoji = "👍"
    elif coverage >= 60:
        grade = "D"
        emoji = "⚠️"
    else:
        grade = "F"
        emoji = "❌"
    
    print(f"\n{Colors.BOLD}Grade: {grade} {emoji}{Colors.END}")
    
    # Recommendations
    if stats['undocumented_items']:
        print(f"\n{Colors.YELLOW}⚠️ Found {len(stats['undocumented_items'])} undocumented items{Colors.END}")
        if verbose:
            print("\nUndocumented items:")
            for item in stats['undocumented_items'][:20]:  # Show first 20
                print(f"  - {item}")
            if len(stats['undocumented_items']) > 20:
                print(f"  ... and {len(stats['undocumented_items']) - 20} more")
    
    print("\n" + "=" * 50)
    
    # Return exit code based on coverage
    return 0 if coverage >= 80 else 1

def main():
    """פונקציה ראשית."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Check documentation coverage for Python project')
    parser.add_argument('--path', default='..', help='Path to project root (default: ..)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')
    parser.add_argument('--min-coverage', type=float, default=80.0, 
                       help='Minimum coverage percentage required (default: 80)')
    
    args = parser.parse_args()
    
    project_root = Path(args.path).resolve()
    
    if not project_root.exists():
        print(f"{Colors.RED}Error: Path {project_root} does not exist{Colors.END}")
        sys.exit(1)
    
    print(f"{Colors.BLUE}Analyzing project at: {project_root}{Colors.END}")
    
    stats = analyze_project(project_root)
    exit_code = print_report(stats, args.verbose)
    
    if stats['overall_coverage'] < args.min_coverage:
        print(f"\n{Colors.RED}❌ Coverage {stats['overall_coverage']:.1f}% is below minimum {args.min_coverage}%{Colors.END}")
        sys.exit(1)
    else:
        print(f"\n{Colors.GREEN}✅ Coverage {stats['overall_coverage']:.1f}% meets minimum requirement{Colors.END}")
        sys.exit(exit_code)

if __name__ == '__main__':
    main()