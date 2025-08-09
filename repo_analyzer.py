"""
מנתח ריפוזיטורי GitHub - מנתח מבנה ומציע שיפורים
"""

import os
import re
import json
import logging
import asyncio
import aiohttp
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse
import base64

logger = logging.getLogger(__name__)

# הגדרות וקבועים
MAX_FILE_SIZE = 100 * 1024  # 100KB
MAX_FILES = 50
GITHUB_API_BASE = "https://api.github.com"
FILE_EXTENSIONS = {
    'python': ['.py', '.pyw'],
    'javascript': ['.js', '.jsx', '.mjs'],
    'typescript': ['.ts', '.tsx'],
    'java': ['.java'],
    'csharp': ['.cs'],
    'cpp': ['.cpp', '.cc', '.cxx', '.hpp', '.h'],
    'go': ['.go'],
    'rust': ['.rs'],
    'ruby': ['.rb'],
    'php': ['.php'],
    'swift': ['.swift'],
    'kotlin': ['.kt', '.kts'],
    'scala': ['.scala'],
    'r': ['.r', '.R'],
    'dart': ['.dart'],
    'lua': ['.lua'],
    'perl': ['.pl', '.pm'],
    'shell': ['.sh', '.bash', '.zsh'],
    'sql': ['.sql'],
    'html': ['.html', '.htm'],
    'css': ['.css', '.scss', '.sass', '.less'],
    'yaml': ['.yaml', '.yml'],
    'json': ['.json'],
    'xml': ['.xml'],
    'markdown': ['.md', '.markdown']
}

DEPENDENCY_FILES = [
    'requirements.txt', 'setup.py', 'pyproject.toml', 'Pipfile',  # Python
    'package.json', 'package-lock.json', 'yarn.lock',  # JavaScript/Node
    'pom.xml', 'build.gradle', 'build.gradle.kts',  # Java
    'Cargo.toml',  # Rust
    'go.mod', 'go.sum',  # Go
    'composer.json',  # PHP
    'Gemfile', 'Gemfile.lock',  # Ruby
    '.csproj', 'packages.config',  # C#
    'pubspec.yaml',  # Dart/Flutter
]

IMPORTANT_FILES = ['README.md', 'LICENSE', '.gitignore', 'CONTRIBUTING.md', 'CODE_OF_CONDUCT.md']


class RepoAnalyzer:
    """מחלקה לניתוח ריפוזיטורי GitHub"""
    
    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or os.getenv('GITHUB_TOKEN')
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'CodeKeeperBot-RepoAnalyzer'
        }
        if self.github_token:
            self.headers['Authorization'] = f'token {self.github_token}'
    
    def set_token(self, token: str):
        """עדכון הטוקן בזמן ריצה"""
        self.github_token = token
        if token:
            self.headers['Authorization'] = f'token {token}'
        elif 'Authorization' in self.headers:
            del self.headers['Authorization']
    
    async def fetch_and_analyze_repo(self, url: str) -> Dict[str, Any]:
        """
        שולף ומנתח ריפוזיטורי GitHub
        
        Args:
            url: URL של הריפוזיטורי
            
        Returns:
            Dictionary עם תוצאות הניתוח
        """
        try:
            # פרסור URL
            owner, repo = self._parse_github_url(url)
            if not owner or not repo:
                return {'error': 'URL לא תקין. דוגמה: https://github.com/owner/repo'}
            
            async with aiohttp.ClientSession() as session:
                # שלב 1: קבלת מידע בסיסי על הריפו
                repo_info = await self._fetch_repo_info(session, owner, repo)
                if 'error' in repo_info:
                    return repo_info
                
                # שלב 2: קבלת מבנה הריפו (עומק 1)
                tree = await self._fetch_repo_tree(session, owner, repo)
                if 'error' in tree:
                    return tree
                
                # שלב 3: הורדת קבצים רלוונטיים
                files_content = await self._fetch_relevant_files(session, owner, repo, tree)
                
                # שלב 4: ניתוח הממצאים
                analysis = self._analyze_repo_data(repo_info, tree, files_content)
                
                return {
                    'success': True,
                    'repo_url': url,
                    'owner': owner,
                    'repo_name': repo,
                    'repo_info': repo_info,
                    'analysis': analysis,
                    'files_content': files_content  # למקרה שנרצה לנתח יותר לעומק
                }
                
        except Exception as e:
            logger.error(f"Error analyzing repo {url}: {e}")
            return {'error': f'שגיאה בניתוח הריפו: {str(e)}'}
    
    def _parse_github_url(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """פרסור URL של GitHub לקבלת owner ו-repo"""
        patterns = [
            r'github\.com/([^/]+)/([^/\?#]+)',
            r'github\.com:([^/]+)/([^/\?#]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                owner, repo = match.groups()
                # הסרת .git אם קיים
                repo = repo.replace('.git', '')
                return owner, repo
        
        return None, None
    
    async def _fetch_repo_info(self, session: aiohttp.ClientSession, owner: str, repo: str) -> Dict:
        """שליפת מידע בסיסי על הריפו"""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        
        try:
            async with session.get(url, headers=self.headers) as response:
                if response.status == 404:
                    return {'error': 'ריפוזיטורי לא נמצא או פרטי'}
                elif response.status == 403:
                    return {'error': 'חריגת מגבלת API של GitHub'}
                elif response.status != 200:
                    return {'error': f'שגיאה בקבלת מידע: {response.status}'}
                
                return await response.json()
        except Exception as e:
            return {'error': f'שגיאה בחיבור ל-GitHub: {str(e)}'}
    
    async def _fetch_repo_tree(self, session: aiohttp.ClientSession, owner: str, repo: str) -> Dict:
        """שליפת מבנה הריפו (עומק 1)"""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents"
        
        try:
            async with session.get(url, headers=self.headers) as response:
                if response.status != 200:
                    return {'error': f'שגיאה בקבלת מבנה הריפו: {response.status}'}
                
                return {'items': await response.json()}
        except Exception as e:
            return {'error': f'שגיאה בקבלת מבנה: {str(e)}'}
    
    async def _fetch_relevant_files(self, session: aiohttp.ClientSession, owner: str, repo: str, tree: Dict) -> Dict[str, Any]:
        """הורדת קבצים רלוונטיים"""
        files_content = {}
        files_downloaded = 0
        
        if 'error' in tree:
            return files_content
        
        # רשימת קבצים להורדה
        files_to_download = []
        
        for item in tree.get('items', []):
            if files_downloaded >= MAX_FILES:
                break
                
            if item['type'] != 'file':
                continue
                
            file_name = item['name']
            file_size = item.get('size', 0)
            
            # דלג על קבצים גדולים מדי
            if file_size > MAX_FILE_SIZE:
                continue
            
            # בדוק אם זה קובץ רלוונטי
            is_relevant = False
            
            # קבצים חשובים
            if file_name in IMPORTANT_FILES or file_name in DEPENDENCY_FILES:
                is_relevant = True
            
            # קבצי קוד
            if not is_relevant:
                for lang, extensions in FILE_EXTENSIONS.items():
                    if any(file_name.endswith(ext) for ext in extensions):
                        is_relevant = True
                        break
            
            if is_relevant:
                files_to_download.append(item)
        
        # הורדת הקבצים במקביל
        tasks = []
        for file_item in files_to_download[:MAX_FILES]:
            task = self._fetch_file_content(session, file_item['download_url'], file_item['name'])
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if not isinstance(result, Exception) and result:
                file_name = files_to_download[i]['name']
                files_content[file_name] = result
        
        return files_content
    
    async def _fetch_file_content(self, session: aiohttp.ClientSession, url: str, file_name: str) -> Optional[Dict]:
        """הורדת תוכן קובץ בודד"""
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.text()
                    lines = content.split('\n')
                    return {
                        'content': content[:5000] if len(content) > 5000 else content,  # הגבלה ל-5000 תווים
                        'lines_count': len(lines),
                        'size': len(content),
                        'truncated': len(content) > 5000
                    }
        except Exception as e:
            logger.error(f"Error fetching file {file_name}: {e}")
            return None
    
    def _analyze_repo_data(self, repo_info: Dict, tree: Dict, files_content: Dict) -> Dict:
        """ניתוח הנתונים שנאספו"""
        analysis = {
            'has_readme': False,
            'has_license': False,
            'has_gitignore': False,
            'has_contributing': False,
            'has_code_of_conduct': False,
            'has_tests': False,
            'has_ci_cd': False,
            'languages': {},
            'dependency_files': [],
            'large_files': [],
            'long_functions': [],
            'total_files': 0,
            'total_directories': 0,
            'structure': [],
            'dependencies': {},
            'suggestions_data': {}  # נתונים נוספים לצורך הצעות
        }
        
        # ניתוח מידע בסיסי מהריפו
        if repo_info and 'error' not in repo_info:
            analysis['stars'] = repo_info.get('stargazers_count', 0)
            analysis['forks'] = repo_info.get('forks_count', 0)
            analysis['open_issues'] = repo_info.get('open_issues_count', 0)
            analysis['created_at'] = repo_info.get('created_at')
            analysis['updated_at'] = repo_info.get('updated_at')
            analysis['default_branch'] = repo_info.get('default_branch', 'main')
            analysis['description'] = repo_info.get('description', '')
            analysis['topics'] = repo_info.get('topics', [])
        
        # ניתוח מבנה הריפו
        if tree and 'items' in tree:
            for item in tree['items']:
                if item['type'] == 'file':
                    analysis['total_files'] += 1
                    file_name = item['name']
                    
                    # בדיקת קבצים חשובים
                    if file_name.upper() == 'README.MD' or file_name == 'README':
                        analysis['has_readme'] = True
                    elif file_name.upper() == 'LICENSE' or file_name.upper().startswith('LICENSE.'):
                        analysis['has_license'] = True
                    elif file_name == '.gitignore':
                        analysis['has_gitignore'] = True
                    elif file_name.upper() == 'CONTRIBUTING.MD':
                        analysis['has_contributing'] = True
                    elif file_name.upper() == 'CODE_OF_CONDUCT.MD':
                        analysis['has_code_of_conduct'] = True
                    
                    # בדיקת CI/CD
                    if file_name in ['.travis.yml', '.circleci', 'Jenkinsfile', 'azure-pipelines.yml']:
                        analysis['has_ci_cd'] = True
                    
                    # ספירת שפות
                    for lang, extensions in FILE_EXTENSIONS.items():
                        if any(file_name.endswith(ext) for ext in extensions):
                            analysis['languages'][lang] = analysis['languages'].get(lang, 0) + 1
                    
                    # זיהוי קבצי תלויות
                    if file_name in DEPENDENCY_FILES:
                        analysis['dependency_files'].append(file_name)
                    
                    # זיהוי קבצים גדולים
                    file_size = item.get('size', 0)
                    if file_size > 50000:  # קבצים מעל 50KB
                        analysis['large_files'].append({
                            'name': file_name,
                            'size': file_size,
                            'size_kb': round(file_size / 1024, 2)
                        })
                
                elif item['type'] == 'dir':
                    analysis['total_directories'] += 1
                    dir_name = item['name']
                    
                    # בדיקת תיקיות מיוחדות
                    if dir_name in ['test', 'tests', 'spec', 'specs', '__tests__']:
                        analysis['has_tests'] = True
                    elif dir_name == '.github':
                        analysis['has_ci_cd'] = True  # GitHub Actions
                    
                    analysis['structure'].append({'type': 'dir', 'name': dir_name})
        
        # ניתוח תוכן הקבצים
        for file_name, content_data in files_content.items():
            if content_data and 'content' in content_data:
                content = content_data.get('content', '')
                lines_count = content_data.get('lines_count', 0)
                
                # זיהוי פונקציות ארוכות (פשוט - ספירת שורות בין def/function)
                if file_name.endswith('.py'):
                    functions = re.findall(r'def\s+(\w+)\s*\([^)]*\):', content)
                    if lines_count > 500:
                        analysis['long_functions'].append({
                            'file': file_name,
                            'lines': lines_count,
                            'functions_found': len(functions)
                        })
                
                # ניתוח קבצי תלויות
                if file_name == 'requirements.txt':
                    deps = self._parse_requirements(content)
                    analysis['dependencies']['python'] = deps
                elif file_name == 'package.json':
                    deps = self._parse_package_json(content)
                    analysis['dependencies']['npm'] = deps
        
        return analysis
    
    def _parse_requirements(self, content: str) -> List[Dict]:
        """פרסור requirements.txt"""
        dependencies = []
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                # פרסור בסיסי של תלות
                match = re.match(r'^([a-zA-Z0-9\-_]+)([><=~!]+.*)?', line)
                if match:
                    name = match.group(1)
                    version = match.group(2) or ''
                    dependencies.append({
                        'name': name,
                        'version': version.strip() if version else 'any'
                    })
        return dependencies
    
    def _parse_package_json(self, content: str) -> List[Dict]:
        """פרסור package.json"""
        dependencies = []
        try:
            data = json.loads(content)
            for dep_type in ['dependencies', 'devDependencies']:
                if dep_type in data:
                    for name, version in data[dep_type].items():
                        dependencies.append({
                            'name': name,
                            'version': version,
                            'dev': dep_type == 'devDependencies'
                        })
        except json.JSONDecodeError:
            pass
        return dependencies
    
    def generate_improvement_suggestions(self, analysis_data: Dict) -> List[Dict]:
        """
        יצירת הצעות לשיפור על בסיס הניתוח
        
        Args:
            analysis_data: תוצאות הניתוח מ-fetch_and_analyze_repo
            
        Returns:
            רשימת הצעות לשיפור
        """
        suggestions = []
        
        if 'error' in analysis_data:
            return suggestions
        
        analysis = analysis_data.get('analysis', {})
        
        # בדיקת קבצים חסרים חשובים
        if not analysis.get('has_license'):
            suggestions.append({
                'id': 'add_license',
                'title': '🔒 הוסף קובץ LICENSE',
                'why': 'פרויקט ללא רישיון = כל הזכויות שמורות. זה מונע מאחרים להשתמש בקוד',
                'how': 'הוסף קובץ LICENSE עם רישיון מתאים (MIT/Apache 2.0/GPL)',
                'impact': 'high',
                'effort': 'low',
                'category': 'legal'
            })
        
        if not analysis.get('has_readme'):
            suggestions.append({
                'id': 'add_readme',
                'title': '📝 הוסף קובץ README.md',
                'why': 'README הוא הפנים של הפרויקט - בלעדיו אף אחד לא יבין מה הפרויקט עושה',
                'how': 'צור README.md עם: תיאור, התקנה, שימוש, תרומה',
                'impact': 'high',
                'effort': 'medium',
                'category': 'documentation'
            })
        elif analysis.get('has_readme'):
            # בדוק אם README קצר מדי
            readme_content = analysis_data.get('files_content', {}).get('README.md', {})
            if readme_content and readme_content.get('lines_count', 0) < 10:
                suggestions.append({
                    'id': 'improve_readme',
                    'title': '📝 שפר את ה-README',
                    'why': 'README קצר מדי - חסר מידע חשוב למשתמשים',
                    'how': 'הוסף: דוגמאות קוד, תמונות, badges, רשימת features',
                    'impact': 'medium',
                    'effort': 'medium',
                    'category': 'documentation'
                })
        
        if not analysis.get('has_gitignore'):
            suggestions.append({
                'id': 'add_gitignore',
                'title': '🔧 הוסף קובץ .gitignore',
                'why': 'מונע העלאת קבצים לא רצויים ל-Git (node_modules, __pycache__, .env)',
                'how': 'צור .gitignore מתאים לשפה. השתמש ב-gitignore.io',
                'impact': 'medium',
                'effort': 'low',
                'category': 'configuration'
            })
        
        # בדיקת תלויות
        if 'python' in analysis.get('dependencies', {}):
            deps = analysis['dependencies']['python']
            unpinned = [d for d in deps if d.get('version') == 'any' or not d.get('version')]
            if unpinned:
                suggestions.append({
                    'id': 'pin_dependencies',
                    'title': '📦 נעל גרסאות תלויות Python',
                    'why': f'יש {len(unpinned)} תלויות ללא גרסה מוגדרת - עלול לגרום לבעיות תאימות',
                    'how': 'הוסף גרסאות מדויקות או טווחים ב-requirements.txt',
                    'impact': 'medium',
                    'effort': 'low',
                    'category': 'dependencies'
                })
        
        if 'npm' in analysis.get('dependencies', {}):
            deps = analysis['dependencies']['npm']
            if deps and not any('package-lock.json' in f for f in analysis.get('dependency_files', [])):
                suggestions.append({
                    'id': 'add_lockfile',
                    'title': '📦 הוסף package-lock.json',
                    'why': 'חסר קובץ נעילת גרסאות - עלול לגרום לבעיות בהתקנה',
                    'how': 'הרץ npm install להפקת package-lock.json',
                    'impact': 'medium',
                    'effort': 'low',
                    'category': 'dependencies'
                })
        
        # בדיקת CI/CD
        if not analysis.get('has_ci_cd'):
            suggestions.append({
                'id': 'add_ci_cd',
                'title': '🔄 הוסף GitHub Actions CI/CD',
                'why': 'אוטומציה של בדיקות ו-deployment חוסכת זמן ומונעת באגים',
                'how': 'צור .github/workflows עם בדיקות אוטומטיות',
                'impact': 'high',
                'effort': 'medium',
                'category': 'automation'
            })
        
        # בדיקת בדיקות
        if not analysis.get('has_tests'):
            suggestions.append({
                'id': 'add_tests',
                'title': '🧪 הוסף בדיקות לפרויקט',
                'why': 'בדיקות מבטיחות שהקוד עובד ומונעות רגרסיות',
                'how': 'צור תיקיית tests עם בדיקות יחידה בסיסיות',
                'impact': 'high',
                'effort': 'high',
                'category': 'quality'
            })
        
        # בדיקת קבצים גדולים
        large_files = analysis.get('large_files', [])
        if large_files:
            largest = max(large_files, key=lambda x: x['size'])
            suggestions.append({
                'id': 'split_large_files',
                'title': f'⚡ פצל קבצים גדולים',
                'why': f'יש {len(large_files)} קבצים גדולים (הגדול: {largest["name"]} - {largest["size_kb"]}KB)',
                'how': 'פצל לפונקציות/מודולים קטנים יותר לשיפור תחזוקה',
                'impact': 'medium',
                'effort': 'medium',
                'category': 'refactoring'
            })
        
        # בדיקת פונקציות ארוכות
        long_functions = analysis.get('long_functions', [])
        if long_functions:
            suggestions.append({
                'id': 'refactor_long_functions',
                'title': '🔨 פרק פונקציות ארוכות',
                'why': f'יש {len(long_functions)} קבצים עם יותר מ-500 שורות',
                'how': 'פרק לפונקציות קטנות יותר (מקסימום 50 שורות)',
                'impact': 'medium',
                'effort': 'high',
                'category': 'refactoring'
            })
        
        # בדיקת תיעוד תרומה
        if not analysis.get('has_contributing'):
            suggestions.append({
                'id': 'add_contributing',
                'title': '🤝 הוסף CONTRIBUTING.md',
                'why': 'מסביר איך לתרום לפרויקט - מעודד קהילה',
                'how': 'צור CONTRIBUTING.md עם הנחיות לתורמים',
                'impact': 'low',
                'effort': 'low',
                'category': 'community'
            })
        
        # בדיקת קוד התנהגות
        if not analysis.get('has_code_of_conduct'):
            suggestions.append({
                'id': 'add_code_of_conduct',
                'title': '👥 הוסף CODE_OF_CONDUCT.md',
                'why': 'מגדיר כללי התנהגות בקהילה - יוצר סביבה בטוחה',
                'how': 'השתמש בתבנית מ-GitHub או Contributor Covenant',
                'impact': 'low',
                'effort': 'low',
                'category': 'community'
            })
        
        # בדיקת עדכניות (אם יש תאריך עדכון אחרון)
        if analysis.get('updated_at'):
            try:
                last_update = datetime.fromisoformat(analysis['updated_at'].replace('Z', '+00:00'))
                days_since_update = (datetime.now(last_update.tzinfo) - last_update).days
                if days_since_update > 365:
                    suggestions.append({
                        'id': 'update_project',
                        'title': '⬆️ עדכן את הפרויקט',
                        'why': f'הפרויקט לא עודכן {days_since_update} ימים - עלול להכיל תלויות מיושנות',
                        'how': 'עדכן תלויות, תקן באגים, הוסף features חדשים',
                        'impact': 'high',
                        'effort': 'medium',
                        'category': 'maintenance'
                    })
            except:
                pass
        
        # בדיקת תיאור
        if not analysis.get('description'):
            suggestions.append({
                'id': 'add_description',
                'title': '📋 הוסף תיאור לריפוזיטורי',
                'why': 'תיאור קצר עוזר להבין במהירות מה הפרויקט עושה',
                'how': 'הוסף תיאור בהגדרות הריפו ב-GitHub',
                'impact': 'low',
                'effort': 'low',
                'category': 'metadata'
            })
        
        # בדיקת topics/tags
        if not analysis.get('topics'):
            suggestions.append({
                'id': 'add_topics',
                'title': '🏷️ הוסף תגיות (topics)',
                'why': 'תגיות עוזרות לאנשים למצוא את הפרויקט',
                'how': 'הוסף topics רלוונטיים בהגדרות הריפו',
                'impact': 'low',
                'effort': 'low',
                'category': 'metadata'
            })
        
        # מיון לפי חשיבות (impact) ומאמץ (effort)
        priority_order = {
            ('high', 'low'): 1,
            ('high', 'medium'): 2,
            ('medium', 'low'): 3,
            ('high', 'high'): 4,
            ('medium', 'medium'): 5,
            ('low', 'low'): 6,
            ('medium', 'high'): 7,
            ('low', 'medium'): 8,
            ('low', 'high'): 9
        }
        
        suggestions.sort(key=lambda x: priority_order.get((x['impact'], x['effort']), 10))
        
        return suggestions


# יצירת instance גלובלי
repo_analyzer = RepoAnalyzer()


async def fetch_and_analyze_repo(url: str) -> Dict[str, Any]:
    """פונקציה עוטפת לשימוש בבוט"""
    return await repo_analyzer.fetch_and_analyze_repo(url)


def generate_improvement_suggestions(analysis_data: Dict) -> List[Dict]:
    """פונקציה עוטפת לשימוש בבוט"""
    return repo_analyzer.generate_improvement_suggestions(analysis_data)