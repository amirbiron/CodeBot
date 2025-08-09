"""
GitHub Repository Analyzer Module
ניתוח ריפוזיטוריים ב-GitHub והצעות שיפור
"""

import os
import logging
import asyncio
import aiohttp
import base64
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import json
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class RepoAnalyzer:
    """מנתח ריפוזיטוריים ב-GitHub"""
    
    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or os.getenv('GITHUB_TOKEN')
        self.session = None
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'CodeKeeperBot/1.0'
        }
        if self.github_token:
            self.headers['Authorization'] = f'token {self.github_token}'
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _parse_github_url(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """מחלץ owner ו-repo מ-URL של GitHub"""
        try:
            parsed = urlparse(url)
            if parsed.netloc not in ['github.com', 'www.github.com']:
                return None, None
            
            parts = parsed.path.strip('/').split('/')
            if len(parts) >= 2:
                return parts[0], parts[1]
            return None, None
        except Exception as e:
            logger.error(f"Error parsing GitHub URL: {e}")
            return None, None
    
    async def fetch_and_analyze_repo(self, url: str) -> Dict:
        """שולף ומנתח ריפוזיטורי מ-GitHub"""
        owner, repo = self._parse_github_url(url)
        if not owner or not repo:
            raise ValueError("Invalid GitHub repository URL")
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            self.session = session
            
            try:
                # שלוף מידע בסיסי על הריפו
                repo_info = await self._fetch_repo_info(owner, repo)
                
                # שלוף מבנה תיקיות (עומק 1)
                tree_data = await self._fetch_repo_tree(owner, repo, repo_info.get('default_branch', 'main'))
                
                # נתח קבצים רלוונטיים
                files_analysis = await self._analyze_files(owner, repo, tree_data)
                
                # בנה דוח ניתוח
                analysis = {
                    'repo_url': url,
                    'owner': owner,
                    'name': repo,
                    'description': repo_info.get('description', ''),
                    'stars': repo_info.get('stargazers_count', 0),
                    'forks': repo_info.get('forks_count', 0),
                    'language': repo_info.get('language', 'Unknown'),
                    'created_at': repo_info.get('created_at', ''),
                    'updated_at': repo_info.get('updated_at', ''),
                    'default_branch': repo_info.get('default_branch', 'main'),
                    'has_readme': files_analysis['has_readme'],
                    'has_license': files_analysis['has_license'],
                    'has_gitignore': files_analysis['has_gitignore'],
                    'file_counts': files_analysis['file_counts'],
                    'dependencies': files_analysis['dependencies'],
                    'large_files': files_analysis['large_files'],
                    'long_functions': files_analysis['long_functions'],
                    'directory_structure': files_analysis['directory_structure'],
                    'total_files': files_analysis['total_files'],
                    'total_size': files_analysis['total_size'],
                    'has_tests': files_analysis['has_tests'],
                    'has_ci': files_analysis['has_ci'],
                    'analyzed_at': datetime.now().isoformat()
                }
                
                return analysis
                
            except aiohttp.ClientError as e:
                logger.error(f"API request failed: {e}")
                raise Exception(f"Failed to fetch repository: {str(e)}")
            except Exception as e:
                logger.error(f"Analysis failed: {e}")
                raise
    
    async def _fetch_repo_info(self, owner: str, repo: str) -> Dict:
        """שולף מידע בסיסי על הריפו"""
        url = f"https://api.github.com/repos/{owner}/{repo}"
        async with self.session.get(url) as response:
            if response.status == 404:
                raise ValueError("Repository not found or private")
            elif response.status == 403:
                raise ValueError("API rate limit exceeded")
            elif response.status != 200:
                raise ValueError(f"GitHub API error: {response.status}")
            return await response.json()
    
    async def _fetch_repo_tree(self, owner: str, repo: str, branch: str) -> Dict:
        """שולף את מבנה הקבצים של הריפו"""
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        async with self.session.get(url) as response:
            if response.status != 200:
                raise ValueError(f"Failed to fetch repository tree: {response.status}")
            return await response.json()
    
    async def _fetch_file_content(self, owner: str, repo: str, path: str) -> Optional[str]:
        """שולף תוכן של קובץ ספציפי"""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                if data.get('encoding') == 'base64' and 'content' in data:
                    content = base64.b64decode(data['content']).decode('utf-8', errors='ignore')
                    return content
                return None
        except Exception as e:
            logger.error(f"Error fetching file {path}: {e}")
            return None
    
    async def _analyze_files(self, owner: str, repo: str, tree_data: Dict) -> Dict:
        """מנתח את הקבצים בריפו"""
        analysis = {
            'has_readme': False,
            'has_license': False,
            'has_gitignore': False,
            'has_tests': False,
            'has_ci': False,
            'file_counts': {},
            'dependencies': {},
            'large_files': [],
            'long_functions': [],
            'directory_structure': [],
            'total_files': 0,
            'total_size': 0
        }
        
        # קבצי קוד רלוונטיים
        code_extensions = {
            '.py': 'Python',
            '.js': 'JavaScript',
            '.ts': 'TypeScript',
            '.java': 'Java',
            '.cpp': 'C++',
            '.c': 'C',
            '.cs': 'C#',
            '.go': 'Go',
            '.rb': 'Ruby',
            '.php': 'PHP',
            '.swift': 'Swift',
            '.kt': 'Kotlin',
            '.rs': 'Rust',
            '.scala': 'Scala',
            '.r': 'R',
            '.m': 'MATLAB',
            '.jl': 'Julia'
        }
        
        files_to_analyze = []
        directories = set()
        
        # סרוק את העץ
        for item in tree_data.get('tree', []):
            if item['type'] == 'blob':
                path = item['path']
                size = item.get('size', 0)
                
                # בדוק קבצים מיוחדים
                if path.lower() == 'readme.md' or path.lower() == 'readme':
                    analysis['has_readme'] = True
                elif path.lower() == 'license' or path.lower() == 'license.md':
                    analysis['has_license'] = True
                elif path == '.gitignore':
                    analysis['has_gitignore'] = True
                elif 'test' in path.lower() or 'spec' in path.lower():
                    analysis['has_tests'] = True
                elif '.github/workflows' in path or '.gitlab-ci' in path or 'travis.yml' in path:
                    analysis['has_ci'] = True
                
                # ספור קבצים לפי סוג
                ext = os.path.splitext(path)[1].lower()
                if ext in code_extensions:
                    lang = code_extensions[ext]
                    analysis['file_counts'][lang] = analysis['file_counts'].get(lang, 0) + 1
                    
                    # הוסף לרשימת קבצים לניתוח (מקסימום 50)
                    if len(files_to_analyze) < 50 and size < 100 * 1024:  # 100KB
                        files_to_analyze.append((path, size))
                    
                    # זהה קבצים גדולים
                    if size > 50 * 1024:  # 50KB
                        analysis['large_files'].append({
                            'path': path,
                            'size': size,
                            'size_kb': round(size / 1024, 1)
                        })
                
                # בדוק קבצי תלויות
                if path in ['requirements.txt', 'package.json', 'pyproject.toml', 'Pipfile', 
                           'Gemfile', 'go.mod', 'pom.xml', 'build.gradle', 'Cargo.toml']:
                    content = await self._fetch_file_content(owner, repo, path)
                    if content:
                        deps = self._parse_dependencies(path, content)
                        if deps:
                            analysis['dependencies'][path] = deps
                
                # עדכן סטטיסטיקות
                analysis['total_files'] += 1
                analysis['total_size'] += size
                
                # אסוף מבנה תיקיות
                dir_path = os.path.dirname(path)
                if dir_path and dir_path not in directories:
                    directories.add(dir_path)
        
        # נתח קבצי קוד לפונקציות ארוכות
        tasks = []
        for file_path, size in files_to_analyze[:20]:  # מקסימום 20 קבצים
            tasks.append(self._analyze_code_file(owner, repo, file_path))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, dict) and result.get('long_functions'):
                analysis['long_functions'].extend(result['long_functions'])
        
        # בנה מבנה תיקיות
        analysis['directory_structure'] = sorted(list(directories))[:20]  # מקסימום 20 תיקיות
        
        return analysis
    
    async def _analyze_code_file(self, owner: str, repo: str, path: str) -> Dict:
        """מנתח קובץ קוד ספציפי"""
        content = await self._fetch_file_content(owner, repo, path)
        if not content:
            return {}
        
        lines = content.split('\n')
        result = {'long_functions': []}
        
        # זיהוי פשוט של פונקציות ארוכות
        in_function = False
        function_start = 0
        function_name = ''
        
        for i, line in enumerate(lines):
            # זיהוי תחילת פונקציה (פשוט)
            if any(keyword in line for keyword in ['def ', 'function ', 'func ', 'fn ', 'public ', 'private ']):
                if in_function and i - function_start > 50:
                    result['long_functions'].append({
                        'file': path,
                        'name': function_name,
                        'lines': i - function_start,
                        'start_line': function_start + 1
                    })
                in_function = True
                function_start = i
                # נסה לחלץ שם פונקציה
                function_name = line.strip().split('(')[0].split()[-1] if '(' in line else 'unknown'
            
            # זיהוי סוף פונקציה (פשוט - שורה ריקה אחרי פונקציה)
            elif in_function and line.strip() == '' and i > function_start + 1:
                if i - function_start > 50:
                    result['long_functions'].append({
                        'file': path,
                        'name': function_name,
                        'lines': i - function_start,
                        'start_line': function_start + 1
                    })
                in_function = False
        
        # בדוק פונקציה אחרונה
        if in_function and len(lines) - function_start > 50:
            result['long_functions'].append({
                'file': path,
                'name': function_name,
                'lines': len(lines) - function_start,
                'start_line': function_start + 1
            })
        
        return result
    
    def _parse_dependencies(self, filename: str, content: str) -> List[str]:
        """מחלץ רשימת תלויות מקובץ"""
        dependencies = []
        
        try:
            if filename == 'requirements.txt':
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # הסר גרסאות ותנאים
                        dep = line.split('==')[0].split('>=')[0].split('<=')[0].split('>')[0].split('<')[0].split('[')[0]
                        if dep:
                            dependencies.append(dep)
            
            elif filename == 'package.json':
                data = json.loads(content)
                deps = data.get('dependencies', {})
                dev_deps = data.get('devDependencies', {})
                dependencies = list(deps.keys()) + list(dev_deps.keys())
            
            elif filename == 'pyproject.toml':
                # ניתוח פשוט של TOML
                in_dependencies = False
                for line in content.split('\n'):
                    if '[tool.poetry.dependencies]' in line or '[project.dependencies]' in line:
                        in_dependencies = True
                    elif line.startswith('[') and in_dependencies:
                        in_dependencies = False
                    elif in_dependencies and '=' in line:
                        dep = line.split('=')[0].strip().strip('"')
                        if dep and not dep.startswith('python'):
                            dependencies.append(dep)
            
            # קבצים נוספים - פשוט החזר שיש תלויות
            elif filename in ['Pipfile', 'Gemfile', 'go.mod', 'pom.xml', 'build.gradle', 'Cargo.toml']:
                dependencies.append(f"Dependencies in {filename}")
        
        except Exception as e:
            logger.error(f"Error parsing dependencies from {filename}: {e}")
        
        return dependencies[:20]  # מקסימום 20 תלויות


def generate_improvement_suggestions(analysis_data: Dict) -> List[Dict]:
    """מייצר הצעות לשיפור הריפוזיטורי"""
    suggestions = []
    
    # בדוק קבצים חסרים
    if not analysis_data.get('has_readme'):
        suggestions.append({
            'title': 'הוסף קובץ README',
            'why': 'README הוא הדבר הראשון שמבקרים רואים. הוא מסביר מה הפרויקט עושה ואיך להשתמש בו',
            'how': 'צור קובץ README.md עם: תיאור הפרויקט, התקנה, שימוש, תרומה ורישיון',
            'impact': 'high',
            'effort': 'low'
        })
    
    if not analysis_data.get('has_license'):
        suggestions.append({
            'title': 'הוסף קובץ LICENSE',
            'why': 'ללא רישיון, הקוד שלך מוגן בזכויות יוצרים מלאות ואף אחד לא יכול להשתמש בו',
            'how': 'בחר רישיון מתאים (MIT, Apache 2.0, GPL) והוסף קובץ LICENSE',
            'impact': 'high',
            'effort': 'low'
        })
    
    if not analysis_data.get('has_gitignore'):
        suggestions.append({
            'title': 'הוסף קובץ .gitignore',
            'why': 'מונע העלאת קבצים לא רצויים לריפו (כמו node_modules, __pycache__, .env)',
            'how': 'צור .gitignore מתאים לשפה שלך מ-gitignore.io',
            'impact': 'medium',
            'effort': 'low'
        })
    
    # בדוק תלויות
    if analysis_data.get('dependencies'):
        for dep_file, deps in analysis_data['dependencies'].items():
            if dep_file == 'requirements.txt' and deps:
                has_versions = any('==' in str(dep) for dep in deps if isinstance(dep, str))
                if not has_versions:
                    suggestions.append({
                        'title': 'נעל גרסאות בקובץ requirements.txt',
                        'why': 'תלויות ללא גרסאות יכולות להישבר בעתיד כשיצאו גרסאות חדשות',
                        'how': 'השתמש ב-pip freeze > requirements.txt או ציין גרסאות ספציפיות',
                        'impact': 'medium',
                        'effort': 'low'
                    })
                break
    
    # בדוק קבצים גדולים
    large_files = analysis_data.get('large_files', [])
    if large_files:
        largest = max(large_files, key=lambda x: x['size'])
        if largest['size'] > 500 * 1024:  # 500KB
            suggestions.append({
                'title': f'פצל קובץ גדול: {largest["path"]}',
                'why': f'הקובץ גדול מדי ({largest["size_kb"]}KB) וקשה לתחזוקה',
                'how': 'פצל לקבצים קטנים יותר לפי פונקציונליות או מודולים',
                'impact': 'medium',
                'effort': 'medium'
            })
    
    # בדוק פונקציות ארוכות
    long_functions = analysis_data.get('long_functions', [])
    if long_functions:
        longest = max(long_functions, key=lambda x: x['lines'])
        if longest['lines'] > 50:
            suggestions.append({
                'title': f'פצל פונקציה ארוכה: {longest["name"]} ב-{longest["file"]}',
                'why': f'הפונקציה ארוכה מדי ({longest["lines"]} שורות) וקשה להבנה',
                'how': 'פצל לפונקציות קטנות יותר עם אחריות ברורה',
                'impact': 'medium',
                'effort': 'medium'
            })
    
    # בדוק בדיקות
    if not analysis_data.get('has_tests'):
        suggestions.append({
            'title': 'הוסף בדיקות (Tests)',
            'why': 'בדיקות מבטיחות שהקוד עובד כמצופה ומונעות באגים בעתיד',
            'how': 'צור תיקיית tests והוסף בדיקות יחידה לפונקציות העיקריות',
            'impact': 'high',
            'effort': 'high'
        })
    
    # בדוק CI/CD
    if not analysis_data.get('has_ci'):
        suggestions.append({
            'title': 'הוסף GitHub Actions CI/CD',
            'why': 'אוטומציה של בדיקות ו-deployment חוסכת זמן ומונעת שגיאות',
            'how': 'צור .github/workflows/ci.yml עם בדיקות אוטומטיות',
            'impact': 'high',
            'effort': 'medium'
        })
    
    # בדוק עדכון אחרון
    if analysis_data.get('updated_at'):
        try:
            updated = datetime.fromisoformat(analysis_data['updated_at'].replace('Z', '+00:00'))
            if datetime.now(updated.tzinfo) - updated > timedelta(days=365):
                suggestions.append({
                    'title': 'עדכן תלויות ישנות',
                    'why': 'הפרויקט לא עודכן יותר משנה - כנראה יש תלויות ישנות עם באגי אבטחה',
                    'how': 'בדוק עדכונים עם npm outdated או pip list --outdated',
                    'impact': 'high',
                    'effort': 'medium'
                })
        except:
            pass
    
    # בדוק תיעוד בקוד
    if analysis_data.get('file_counts'):
        total_files = sum(analysis_data['file_counts'].values())
        if total_files > 10:
            suggestions.append({
                'title': 'הוסף תיעוד בקוד (Docstrings)',
                'why': 'תיעוד בקוד עוזר למפתחים אחרים (וגם לך בעתיד) להבין את הקוד',
                'how': 'הוסף docstrings לפונקציות ומחלקות עיקריות',
                'impact': 'medium',
                'effort': 'medium'
            })
    
    # מיין לפי חשיבות ומאמץ
    impact_order = {'high': 3, 'medium': 2, 'low': 1}
    effort_order = {'low': 3, 'medium': 2, 'high': 1}
    
    suggestions.sort(key=lambda x: (
        impact_order.get(x['impact'], 0) * effort_order.get(x['effort'], 0)
    ), reverse=True)
    
    return suggestions