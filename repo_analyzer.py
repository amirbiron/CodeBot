import os
import json
import logging
from typing import Dict, List, Any, Optional
from github import Github, GithubException
import base64
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class RepoAnalyzer:
    """מנתח ריפוזיטורי GitHub ומציע שיפורים"""
    
    # הגדרות וקבועים
    MAX_FILE_SIZE = 100 * 1024  # 100KB
    MAX_FILES = 50
    LARGE_FILE_LINES = 500
    LONG_FUNCTION_LINES = 50
    
    # סוגי קבצים לניתוח
    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.cs',
        '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.scala', '.r', '.m'
    }
    
    CONFIG_FILES = {
        'requirements.txt', 'package.json', 'pyproject.toml', 'Pipfile',
        'Cargo.toml', 'go.mod', 'pom.xml', 'build.gradle', 'composer.json',
        'Gemfile', 'Package.swift'
    }
    
    IMPORTANT_FILES = {
        'README.md', 'README.rst', 'README.txt', 'README',
        'LICENSE', 'LICENSE.md', 'LICENSE.txt',
        '.gitignore', '.dockerignore',
        'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
        '.github/workflows', '.gitlab-ci.yml', 'azure-pipelines.yml'
    }
    
    def __init__(self, github_token: Optional[str] = None):
        """אתחול המנתח"""
        self.github_token = github_token
        self.github_client = Github(github_token) if github_token else None
        
    def parse_github_url(self, url: str) -> tuple[str, str]:
        """מחלץ owner ו-repo מ-URL של GitHub"""
        try:
            parsed = urlparse(url)
            path_parts = parsed.path.strip('/').split('/')
            
            if len(path_parts) >= 2:
                owner = path_parts[0]
                repo = path_parts[1].replace('.git', '')
                return owner, repo
            else:
                raise ValueError("Invalid GitHub URL format")
        except Exception as e:
            logger.error(f"Error parsing GitHub URL: {e}")
            raise ValueError(f"לא הצלחתי לנתח את ה-URL: {url}")
    
    async def fetch_and_analyze_repo(self, repo_url: str) -> Dict[str, Any]:
        """שולף ומנתח ריפוזיטורי מ-GitHub"""
        logger.info(f"🔍 Starting analysis of repository: {repo_url}")
        try:
            owner, repo_name = self.parse_github_url(repo_url)
            logger.info(f"📦 Parsed repo: owner={owner}, name={repo_name}")
            
            if not self.github_client:
                raise ValueError("נדרש GitHub token לניתוח ריפוזיטורי")
            
            # קבל את הריפו
            repo = self.github_client.get_repo(f"{owner}/{repo_name}")
            
            analysis = {
                'repo_name': repo.name,
                'repo_url': repo.html_url,
                'description': repo.description,
                'stars': repo.stargazers_count,
                'forks': repo.forks_count,
                'language': repo.language,
                'created_at': repo.created_at.isoformat() if repo.created_at else None,
                'updated_at': repo.updated_at.isoformat() if repo.updated_at else None,
                'has_readme': False,
                'has_license': False,
                'has_gitignore': False,
                'has_ci_cd': False,
                'file_count': 0,
                'files_by_type': {},
                'dependencies': [],
                'large_files': [],
                'long_functions': [],
                'directory_structure': {},
                'test_coverage': False,
                'documentation_quality': 'none',
                'issues_count': repo.open_issues_count,
                'pull_requests_count': 0
            }
            
            # בדוק אם יש LICENSE
            try:
                license_info = repo.get_license()
                if license_info:
                    analysis['has_license'] = True
                    analysis['license_type'] = license_info.license.name
            except:
                pass
            
            # סרוק קבצים בריפו (עומק 1)
            contents = repo.get_contents("")
            files_analyzed = 0
            
            while contents and files_analyzed < self.MAX_FILES:
                file_content = contents.pop(0)
                
                if file_content.type == "dir":
                    # הוסף תיקייה למבנה
                    analysis['directory_structure'][file_content.path] = {
                        'type': 'directory',
                        'name': file_content.name
                    }
                    
                    # בדוק תיקיות מיוחדות
                    if file_content.name in ['tests', 'test', 'spec', '__tests__']:
                        analysis['test_coverage'] = True
                    elif file_content.name == '.github':
                        # בדוק אם יש workflows
                        try:
                            workflows = repo.get_contents(".github/workflows")
                            if workflows:
                                analysis['has_ci_cd'] = True
                        except:
                            pass
                    
                    # הוסף תוכן התיקייה לסריקה (רק עומק 1)
                    if files_analyzed < self.MAX_FILES - 10:  # השאר מקום לקבצים חשובים
                        try:
                            sub_contents = repo.get_contents(file_content.path)
                            contents.extend(sub_contents[:10])  # הגבל תת-תיקיות
                        except:
                            pass
                            
                elif file_content.type == "file":
                    files_analyzed += 1
                    file_name = file_content.name
                    file_path = file_content.path
                    
                    # בדוק קבצים חשובים
                    if file_name.upper() in ['README.MD', 'README.RST', 'README.TXT', 'README']:
                        analysis['has_readme'] = True
                        # נסה לקרוא את ה-README לניתוח איכות
                        try:
                            if file_content.size < 50000:  # מקסימום 50KB
                                readme_content = base64.b64decode(file_content.content).decode('utf-8')
                                analysis['readme_length'] = len(readme_content)
                                # בדוק איכות תיעוד בסיסית
                                if len(readme_content) > 500:
                                    if any(section in readme_content.lower() for section in 
                                          ['installation', 'usage', 'example', 'התקנה', 'שימוש', 'דוגמה']):
                                        analysis['documentation_quality'] = 'good'
                                    else:
                                        analysis['documentation_quality'] = 'basic'
                        except:
                            pass
                    
                    if file_name.upper() in ['LICENSE', 'LICENSE.MD', 'LICENSE.TXT']:
                        analysis['has_license'] = True
                        
                    if file_name == '.gitignore':
                        analysis['has_gitignore'] = True
                    
                    # ספור קבצים לפי סוג
                    ext = os.path.splitext(file_name)[1].lower()
                    if ext in self.CODE_EXTENSIONS:
                        analysis['files_by_type'][ext] = analysis['files_by_type'].get(ext, 0) + 1
                        analysis['file_count'] += 1
                        
                        # בדוק גודל קובץ
                        if file_content.size > 0:
                            try:
                                # נסה לקרוא את הקובץ אם הוא לא גדול מדי
                                if file_content.size < self.MAX_FILE_SIZE:
                                    code_content = base64.b64decode(file_content.content).decode('utf-8')
                                    lines = code_content.split('\n')
                                    line_count = len(lines)
                                    
                                    if line_count > self.LARGE_FILE_LINES:
                                        analysis['large_files'].append({
                                            'path': file_path,
                                            'lines': line_count,
                                            'size': file_content.size
                                        })
                                    
                                    # חפש פונקציות ארוכות (Python/JS)
                                    if ext in ['.py', '.js', '.ts']:
                                        long_funcs = self._find_long_functions(code_content, ext)
                                        analysis['long_functions'].extend(long_funcs)
                            except Exception as e:
                                logger.debug(f"Could not analyze file {file_path}: {e}")
                    
                    # בדוק קבצי תלויות
                    if file_name.lower() in self.CONFIG_FILES:
                        try:
                            if file_content.size < 50000:
                                config_content = base64.b64decode(file_content.content).decode('utf-8')
                                deps = self._extract_dependencies(file_name, config_content)
                                analysis['dependencies'].extend(deps)
                        except:
                            pass
            
            # חשב ציון איכות כללי
            analysis['quality_score'] = self._calculate_quality_score(analysis)
            
            return analysis
            
        except GithubException as e:
            logger.error(f"GitHub API error: {e}")
            raise ValueError(f"שגיאה בגישה לריפוזיטורי: {e.data.get('message', str(e))}")
        except Exception as e:
            logger.error(f"Error analyzing repo: {e}")
            raise ValueError(f"שגיאה בניתוח הריפוזיטורי: {str(e)}")
    
    def _find_long_functions(self, code: str, ext: str) -> List[Dict[str, Any]]:
        """מוצא פונקציות ארוכות בקוד"""
        long_functions = []
        
        try:
            if ext == '.py':
                # חפש פונקציות Python
                pattern = r'^(def|class)\s+(\w+)'
                lines = code.split('\n')
                
                for i, line in enumerate(lines):
                    if re.match(pattern, line):
                        # ספור שורות עד הפונקציה הבאה או סוף הקובץ
                        func_lines = 1
                        indent_level = len(line) - len(line.lstrip())
                        
                        for j in range(i + 1, len(lines)):
                            next_line = lines[j]
                            if next_line.strip():
                                next_indent = len(next_line) - len(next_line.lstrip())
                                if next_indent <= indent_level and re.match(pattern, next_line):
                                    break
                                func_lines += 1
                        
                        if func_lines > self.LONG_FUNCTION_LINES:
                            match = re.match(pattern, line)
                            if match:
                                long_functions.append({
                                    'name': match.group(2),
                                    'type': match.group(1),
                                    'lines': func_lines,
                                    'line_number': i + 1
                                })
                                
            elif ext in ['.js', '.ts']:
                # חפש פונקציות JavaScript/TypeScript
                pattern = r'(function\s+(\w+)|const\s+(\w+)\s*=\s*\(|class\s+(\w+))'
                lines = code.split('\n')
                
                for i, line in enumerate(lines):
                    match = re.search(pattern, line)
                    if match:
                        # ספור שורות בצורה פשוטה (עד הסוגר הסוגר)
                        func_lines = 1
                        brace_count = line.count('{') - line.count('}')
                        
                        for j in range(i + 1, len(lines)):
                            func_lines += 1
                            brace_count += lines[j].count('{') - lines[j].count('}')
                            if brace_count <= 0:
                                break
                        
                        if func_lines > self.LONG_FUNCTION_LINES:
                            func_name = match.group(2) or match.group(3) or match.group(4) or 'anonymous'
                            long_functions.append({
                                'name': func_name,
                                'type': 'function',
                                'lines': func_lines,
                                'line_number': i + 1
                            })
                            
        except Exception as e:
            logger.debug(f"Error finding long functions: {e}")
        
        return long_functions
    
    def _extract_dependencies(self, filename: str, content: str) -> List[Dict[str, str]]:
        """מחלץ תלויות מקבצי קונפיגורציה"""
        dependencies = []
        
        try:
            if filename == 'requirements.txt':
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # נסה לחלץ שם וגרסה
                        parts = re.split(r'[>=<~!]', line)
                        if parts:
                            dependencies.append({
                                'name': parts[0].strip(),
                                'type': 'python',
                                'version': parts[1].strip() if len(parts) > 1 else 'any'
                            })
                            
            elif filename == 'package.json':
                import json
                data = json.loads(content)
                
                for dep_type in ['dependencies', 'devDependencies']:
                    if dep_type in data:
                        for name, version in data[dep_type].items():
                            dependencies.append({
                                'name': name,
                                'type': 'npm',
                                'version': version,
                                'dev': dep_type == 'devDependencies'
                            })
                            
            elif filename == 'pyproject.toml':
                # ניתוח בסיסי של TOML
                in_deps = False
                for line in content.split('\n'):
                    if '[tool.poetry.dependencies]' in line or '[project.dependencies]' in line:
                        in_deps = True
                    elif line.startswith('[') and in_deps:
                        in_deps = False
                    elif in_deps and '=' in line:
                        parts = line.split('=')
                        if len(parts) == 2:
                            name = parts[0].strip().strip('"')
                            version = parts[1].strip().strip('"')
                            if name != 'python':
                                dependencies.append({
                                    'name': name,
                                    'type': 'python',
                                    'version': version
                                })
                                
        except Exception as e:
            logger.debug(f"Error extracting dependencies from {filename}: {e}")
        
        return dependencies
    
    def _calculate_quality_score(self, analysis: Dict[str, Any]) -> int:
        """מחשב ציון איכות כללי (0-100)"""
        score = 0
        
        # קבצים בסיסיים (40 נקודות)
        if analysis['has_readme']:
            score += 15
            if analysis.get('documentation_quality') == 'good':
                score += 10
            elif analysis.get('documentation_quality') == 'basic':
                score += 5
                
        if analysis['has_license']:
            score += 10
        if analysis['has_gitignore']:
            score += 5
        
        # CI/CD ובדיקות (30 נקודות)
        if analysis['has_ci_cd']:
            score += 15
        if analysis['test_coverage']:
            score += 15
        
        # איכות קוד (30 נקודות)
        if not analysis['large_files']:
            score += 10
        elif len(analysis['large_files']) < 3:
            score += 5
            
        if not analysis['long_functions']:
            score += 10
        elif len(analysis['long_functions']) < 3:
            score += 5
        
        # מבנה פרויקט
        if analysis['file_count'] > 0:
            score += 5
        
        # פופולריות (בונוס עד 5 נקודות)
        if analysis.get('stars', 0) > 100:
            score += 5
        elif analysis.get('stars', 0) > 10:
            score += 3
        
        return min(100, score)
    
    def generate_improvement_suggestions(self, analysis_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """מייצר הצעות לשיפור על בסיס הניתוח"""
        suggestions = []
        
        # בדוק קבצים בסיסיים
        if not analysis_data.get('has_license'):
            suggestions.append({
                'id': 'add_license',
                'title': '🔒 הוסף קובץ LICENSE',
                'why': 'פרויקט ללא רישיון = כל הזכויות שמורות. זה מונע מאחרים להשתמש בקוד',
                'how': 'הוסף קובץ LICENSE עם רישיון מתאים (MIT, Apache 2.0, GPL)',
                'impact': 'high',
                'effort': 'low',
                'category': 'legal'
            })
        
        if not analysis_data.get('has_readme'):
            suggestions.append({
                'id': 'add_readme',
                'title': '📝 צור קובץ README',
                'why': 'README הוא הדבר הראשון שאנשים רואים. בלעדיו אף אחד לא יבין מה הפרויקט עושה',
                'how': 'צור README.md עם: תיאור, התקנה, שימוש, דוגמאות',
                'impact': 'high',
                'effort': 'medium',
                'category': 'documentation'
            })
        elif analysis_data.get('documentation_quality') == 'basic':
            suggestions.append({
                'id': 'improve_readme',
                'title': '📚 שפר את ה-README',
                'why': 'README בסיסי לא מספיק מידע למשתמשים',
                'how': 'הוסף: הוראות התקנה, דוגמאות קוד, API reference, תרומה לפרויקט',
                'impact': 'medium',
                'effort': 'medium',
                'category': 'documentation'
            })
        
        if not analysis_data.get('has_gitignore'):
            suggestions.append({
                'id': 'add_gitignore',
                'title': '🔧 הוסף .gitignore',
                'why': 'מונע העלאת קבצים לא רצויים (node_modules, __pycache__, .env)',
                'how': 'צור .gitignore מתאים לשפה. השתמש ב-gitignore.io',
                'impact': 'medium',
                'effort': 'low',
                'category': 'configuration'
            })
        
        # CI/CD ובדיקות
        if not analysis_data.get('has_ci_cd'):
            suggestions.append({
                'id': 'add_ci_cd',
                'title': '🔄 הוסף GitHub Actions CI/CD',
                'why': 'בדיקות אוטומטיות מונעות באגים ומשפרות איכות',
                'how': 'צור .github/workflows עם בדיקות, linting, ו-deployment',
                'impact': 'high',
                'effort': 'medium',
                'category': 'automation'
            })
        
        if not analysis_data.get('test_coverage'):
            suggestions.append({
                'id': 'add_tests',
                'title': '🧪 הוסף בדיקות (tests)',
                'why': 'בדיקות מבטיחות שהקוד עובד ומונעות רגרסיות',
                'how': 'צור תיקיית tests עם unit tests ו-integration tests',
                'impact': 'high',
                'effort': 'high',
                'category': 'quality'
            })
        
        # איכות קוד
        if analysis_data.get('large_files'):
            for file_info in analysis_data['large_files'][:3]:  # מקסימום 3 הצעות
                suggestions.append({
                    'id': f'split_file_{file_info["path"].replace("/", "_")}',
                    'title': f'⚡ פצל קובץ גדול: {file_info["path"]}',
                    'why': f'הקובץ מכיל {file_info["lines"]} שורות. קבצים גדולים קשים לתחזוקה',
                    'how': 'פצל למודולים לוגיים, הפרד concerns, צור קבצי utility',
                    'impact': 'medium',
                    'effort': 'medium',
                    'category': 'refactoring'
                })
        
        if analysis_data.get('long_functions'):
            suggestions.append({
                'id': 'refactor_long_functions',
                'title': f'♻️ פרק פונקציות ארוכות ({len(analysis_data["long_functions"])} פונקציות)',
                'why': 'פונקציות ארוכות (50+ שורות) קשות להבנה ולתחזוקה',
                'how': 'פרק לפונקציות קטנות, השתמש ב-Single Responsibility Principle',
                'impact': 'medium',
                'effort': 'medium',
                'category': 'refactoring'
            })
        
        # תלויות
        deps = analysis_data.get('dependencies', [])
        if deps:
            # בדוק אם יש תלויות ללא גרסה מנעולה
            unpinned = [d for d in deps if d.get('version') in ['*', 'latest', 'any', '']]
            if unpinned:
                suggestions.append({
                    'id': 'pin_dependencies',
                    'title': f'📦 נעל גרסאות תלויות ({len(unpinned)} לא נעולות)',
                    'why': 'תלויות לא נעולות יכולות לגרום לבעיות תאימות',
                    'how': 'ציין גרסאות מדויקות או טווחים (^1.2.3, ~1.2.0)',
                    'impact': 'medium',
                    'effort': 'low',
                    'category': 'dependencies'
                })
        
        # בדוק עדכניות (אם הפרויקט לא עודכן יותר משנה)
        if analysis_data.get('updated_at'):
            try:
                updated = datetime.fromisoformat(analysis_data['updated_at'].replace('Z', '+00:00'))
                if datetime.now(updated.tzinfo) - updated > timedelta(days=365):
                    suggestions.append({
                        'id': 'update_project',
                        'title': '⬆️ עדכן את הפרויקט',
                        'why': 'הפרויקט לא עודכן יותר משנה. ייתכן שיש עדכוני אבטחה',
                        'how': 'עדכן תלויות, בדוק deprecations, הוסף תכונות חדשות',
                        'impact': 'high',
                        'effort': 'high',
                        'category': 'maintenance'
                    })
            except:
                pass
        
        # הוסף המלצות נוספות בהתאם לשפה
        main_language = analysis_data.get('language', '').lower()
        
        if main_language == 'python':
            if not any('black' in d.get('name', '') or 'pylint' in d.get('name', '') 
                      or 'flake8' in d.get('name', '') for d in deps):
                suggestions.append({
                    'id': 'add_linter',
                    'title': '🎨 הוסף linter ו-formatter',
                    'why': 'כלים אלו משפרים איכות ועקביות הקוד',
                    'how': 'הוסף black, pylint או flake8. הגדר ב-CI/CD',
                    'impact': 'medium',
                    'effort': 'low',
                    'category': 'quality'
                })
        
        elif main_language == 'javascript' or main_language == 'typescript':
            if not any('eslint' in d.get('name', '') or 'prettier' in d.get('name', '') 
                      for d in deps):
                suggestions.append({
                    'id': 'add_linter_js',
                    'title': '🎨 הוסף ESLint ו-Prettier',
                    'why': 'כלים אלו משפרים איכות ועקביות הקוד',
                    'how': 'הוסף eslint, prettier. הגדר כללים ב-.eslintrc',
                    'impact': 'medium',
                    'effort': 'low',
                    'category': 'quality'
                })
        
        # הוסף המלצה לתיעוד API אם יש הרבה קבצים
        if analysis_data.get('file_count', 0) > 20:
            suggestions.append({
                'id': 'add_api_docs',
                'title': '📖 הוסף תיעוד API',
                'why': 'פרויקט גדול צריך תיעוד מפורט של הממשקים',
                'how': 'השתמש ב-Sphinx (Python), JSDoc (JS), או כלי דומה',
                'impact': 'medium',
                'effort': 'high',
                'category': 'documentation'
            })
        
        # מיין לפי חשיבות (impact) ומאמץ (effort)
        priority_order = {
            ('high', 'low'): 1,
            ('high', 'medium'): 2,
            ('medium', 'low'): 3,
            ('high', 'high'): 4,
            ('medium', 'medium'): 5,
            ('medium', 'high'): 6,
            ('low', 'low'): 7,
            ('low', 'medium'): 8,
            ('low', 'high'): 9
        }
        
        suggestions.sort(key=lambda x: priority_order.get((x['impact'], x['effort']), 10))
        
        return suggestions