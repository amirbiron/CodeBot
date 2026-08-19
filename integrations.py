"""
אינטגרציות עם שירותים חיצוניים - GitHub Gist, Pastebin, ועוד
External Integrations - GitHub Gist, Pastebin, and more
"""

import asyncio
import base64
import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone, timedelta
import os
from typing import Any, Dict, List, NamedTuple, Optional

import requests
from github import Github, InputFileContent
from github.GithubException import GithubException

from config import config

logger = logging.getLogger(__name__)

try:
    from observability_instrumentation import traced, set_current_span_attributes
except Exception:  # pragma: no cover
    def traced(*_a, **_k):  # type: ignore
        def _inner(f):
            return f
        return _inner

    def set_current_span_attributes(*_a, **_k):  # type: ignore
        return None


def set_span_attrs_quietly(attrs: Dict[str, Any]) -> None:
    """רישום מאפייני span שלא אמור להפיל את הזרימה העסקית.

    טלמטריה היא תוצר לוואי: כשל בה נרשם ל-debug ונבלע, אבל לא בשקט מוחלט —
    ``except: pass`` מסתיר גם באגים אמיתיים בקוד המדידה.
    """
    try:
        set_current_span_attributes(attrs)
    except Exception:
        logger.debug("failed to set span attributes", exc_info=True)


def _get_github_token() -> Optional[str]:
    """השג את טוקן ה-GitHub בצורה חסינה גם כשאין שדה על האובייקט."""

    token = getattr(config, "GITHUB_TOKEN", None)
    if token:
        return token
    # תאימות לאחור: ייתכן שטסטים מזריקים רק משתני סביבה ללא שדה בקונפיג
    return os.getenv("GITHUB_TOKEN")


def _get_pastebin_api_key() -> Optional[str]:
    """השג את מפתח ה-API של Pastebin גם כשאין שדה ישיר על האובייקט."""

    api_key = getattr(config, "PASTEBIN_API_KEY", None)
    if api_key:
        return api_key
    # תאימות לאחור: תמיכה בטסטים שמגדירים רק משתנה סביבה
    return os.getenv("PASTEBIN_API_KEY")


class GitHubGistIntegration:
    """אינטגרציה עם GitHub Gist.

    ``token`` מאפשר לעבוד בשם משתמש מסוים. בלעדיו נופלים לטוקן הגלובלי,
    שנשאר לשימושים תפעוליים בלבד — Gist שנוצר בשם משתמש חייב לעבור דרך
    ``get_gist_integration_for_user`` כדי שלא ייווצר תחת חשבון המערכת.
    """

    def __init__(self, token: Optional[str] = None):
        self.github = None
        self.user = None
        token = token or _get_github_token()
        if token:
            try:
                self.github = Github(token)
                self.user = self.github.get_user()
                logger.debug("GitHub Gist integration ready")
            except GithubException as e:
                logger.error(f"שגיאה בהתחברות ל-GitHub: {e}")
    
    def is_available(self) -> bool:
        """בדיקה אם האינטגרציה זמינה"""
        return self.github is not None and self.user is not None
    
    @traced("integration.github.create_gist")
    def create_gist(self, file_name: str, code: str, language: str, 
                   description: str = "", public: bool = True) -> Optional[Dict[str, Any]]:
        """יצירת Gist חדש"""
        
        if not self.is_available():
            logger.error("GitHub Gist לא זמין - אין טוקן או שגיאה בהתחברות")
            try:
                set_current_span_attributes({"status": "error", "reason": "unavailable"})
            except Exception:
                pass
            return None

        try:
            try:
                set_current_span_attributes({
                    "file_name": str(file_name or ""),
                    "language": str(language or ""),
                    "public": bool(public),
                })
            except Exception:
                pass
            # הכנת תיאור
            if not description:
                description = f"קטע קוד {language} - {file_name}"
            
            # יצירת הקבצים עבור ה-Gist
            files = {file_name: InputFileContent(code)}
            
            # יצירת ה-Gist
            gist = self.user.create_gist(
                public=public,
                files=files,
                description=description
            )
            
            result = {
                "id": gist.id,
                "url": gist.html_url,
                "git_pull_url": gist.git_pull_url,
                "git_push_url": gist.git_push_url,
                "created_at": gist.created_at.isoformat(),
                "description": gist.description,
                "public": gist.public,
                "files": {}
            }
            
            # הוספת מידע על הקבצים
            for name, file_obj in gist.files.items():
                result["files"][name] = {
                    "filename": file_obj.filename,
                    "type": file_obj.type,
                    "language": file_obj.language,
                    "size": file_obj.size,
                    "raw_url": file_obj.raw_url
                }
            
            logger.info(f"נוצר Gist בהצלחה: {gist.html_url}")
            return result
            
        except GithubException as e:
            logger.error(f"שגיאה ביצירת Gist: {e}")
            try:
                set_current_span_attributes({"status": "error", "error_signature": type(e).__name__})
            except Exception:
                pass
            return None
        except Exception as e:
            logger.error(f"שגיאה כללית ביצירת Gist: {e}")
            try:
                set_current_span_attributes({"status": "error", "error_signature": type(e).__name__})
            except Exception:
                pass
            return None

    @traced("integration.github.create_gist_multi")
    def create_gist_multi(self, files_map: Dict[str, str], description: str = "", public: bool = True) -> Optional[Dict[str, Any]]:
        """יצירת Gist עם מספר קבצים"""
        if not self.is_available():
            logger.error("GitHub Gist לא זמין - אין טוקן או שגיאה בהתחברות")
            try:
                set_current_span_attributes({"status": "error", "reason": "unavailable"})
            except Exception:
                pass
            return None
        try:
            if not description:
                description = f"שיתוף קוד מרובה קבצים ({len(files_map)})"

            files: Dict[str, InputFileContent] = {}
            for name, content in files_map.items():
                files[name] = InputFileContent(content)

            gist = self.user.create_gist(
                public=public,
                files=files,
                description=description
            )

            result: Dict[str, Any] = {
                "id": gist.id,
                "url": gist.html_url,
                "git_pull_url": gist.git_pull_url,
                "git_push_url": gist.git_push_url,
                "created_at": gist.created_at.isoformat(),
                "description": gist.description,
                "public": gist.public,
                "files": {}
            }

            for name, file_obj in gist.files.items():
                result["files"][name] = {
                    "filename": file_obj.filename,
                    "type": file_obj.type,
                    "language": file_obj.language,
                    "size": file_obj.size,
                    "raw_url": file_obj.raw_url
                }

            logger.info(f"נוצר Gist מרובה קבצים בהצלחה: {gist.html_url}")
            return result
        except GithubException as e:
            logger.error(f"שגיאה ביצירת Gist מרובה קבצים: {e}")
            try:
                set_current_span_attributes({"status": "error", "error_signature": type(e).__name__})
            except Exception:
                pass
            return None
        except Exception as e:
            logger.error(f"שגיאה כללית ביצירת Gist מרובה קבצים: {e}")
            try:
                set_current_span_attributes({"status": "error", "error_signature": type(e).__name__})
            except Exception:
                pass
            return None
    
    def update_gist(self, gist_id: str, file_name: str, new_code: str) -> Optional[Dict[str, Any]]:
        """עדכון Gist קיים"""
        
        if not self.is_available():
            return None
        
        try:
            gist = self.github.get_gist(gist_id)
            
            # עדכון הקובץ
            files = {
                file_name: {
                    "content": new_code
                }
            }
            
            gist.edit(files=files)
            
            logger.info(f"עודכן Gist: {gist.html_url}")
            return {
                "id": gist.id,
                "url": gist.html_url,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
        except GithubException as e:
            logger.error(f"שגיאה בעדכון Gist: {e}")
            return None
    
    def get_user_gists(self, limit: int = 50) -> List[Dict[str, Any]]:
        """קבלת כל ה-Gists של המשתמש"""
        
        if not self.is_available():
            return []
        
        try:
            gists = []
            for gist in self.user.get_gists()[:limit]:
                gist_data = {
                    "id": gist.id,
                    "description": gist.description,
                    "url": gist.html_url,
                    "public": gist.public,
                    "created_at": gist.created_at.isoformat(),
                    "updated_at": gist.updated_at.isoformat(),
                    "files": list(gist.files.keys())
                }
                gists.append(gist_data)
            
            logger.info(f"נמצאו {len(gists)} Gists")
            return gists
            
        except GithubException as e:
            logger.error(f"שגיאה בקבלת Gists: {e}")
            return []
    
    def delete_gist(self, gist_id: str) -> bool:
        """מחיקת Gist"""
        
        if not self.is_available():
            return False
        
        try:
            gist = self.github.get_gist(gist_id)
            gist.delete()
            
            logger.info(f"נמחק Gist: {gist_id}")
            return True
            
        except GithubException as e:
            logger.error(f"שגיאה במחיקת Gist: {e}")
            return False

class PastebinIntegration:
    """אינטגרציה עם Pastebin"""
    
    def __init__(self):
        self.api_key = _get_pastebin_api_key()
        self.base_url = "https://pastebin.com/api"
        
    def is_available(self) -> bool:
        """בדיקה אם האינטגרציה זמינה"""
        return bool(self.api_key)
    
    @traced("integration.pastebin.create")
    async def create_paste(self, code: str, file_name: str, language: str = None,
                          private: bool = True, expire: str = "1M") -> Optional[Dict[str, Any]]:
        """יצירת paste חדש"""
        
        if not self.is_available():
            logger.error("Pastebin לא זמין - אין API key")
            try:
                set_current_span_attributes({"status": "error", "reason": "unavailable"})
            except Exception:
                pass
            return None
        
        # מיפוי שפות ל-Pastebin format
        language_map = {
            'python': 'python',
            'javascript': 'javascript',
            'java': 'java',
            'cpp': 'cpp',
            'c': 'c',
            'php': 'php',
            'html': 'html5',
            'css': 'css',
            'sql': 'mysql',
            'bash': 'bash',
            'json': 'json',
            'xml': 'xml',
            'yaml': 'yaml',
            'text': 'text'
        }
        
        pastebin_format = language_map.get(language, 'text')
        
        # הכנת הפרמטרים
        data = {
            'api_dev_key': self.api_key,
            'api_option': 'paste',
            'api_paste_code': code,
            'api_paste_name': file_name,
            'api_paste_format': pastebin_format,
            'api_paste_private': '1' if private else '0',  # 0=public, 1=unlisted, 2=private
            'api_paste_expire_date': expire  # N=Never, 10M=10Minutes, 1H=1Hour, 1D=1Day, 1W=1Week, 2W=2Weeks, 1M=1Month, 6M=6Months, 1Y=1Year
        }
        
        try:
            try:
                set_current_span_attributes({
                    "file_name": str(file_name or ""),
                    "language": str(language or ""),
                    "private": bool(private),
                    "expire": str(expire or ""),
                })
            except Exception:
                pass
            from http_async import request as async_request  # lazy import להימנע מתלויות מעגליות
            async with async_request(
                "POST",
                f"{self.base_url}/api_post.php",
                data=data,
                service="pastebin",
                endpoint="create_paste",
            ) as response:
                    result = await response.text()
                    
                    if response.status == 200 and result.startswith('https://pastebin.com/'):
                        logger.info(f"נוצר Pastebin paste: {result}")
                        
                        # חילוץ ID מה-URL
                        paste_id = result.split('/')[-1]
                        
                        return {
                            "id": paste_id,
                            "url": result,
                            "raw_url": f"https://pastebin.com/raw/{paste_id}",
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "private": private,
                            "expire": expire,
                            "language": pastebin_format
                        }
                    else:
                        logger.error(f"שגיאה ביצירת Pastebin paste: {result}")
                        try:
                            set_current_span_attributes({"status": "error", "error_signature": "PastebinError"})
                        except Exception:
                            pass
                        return None
                        
        except Exception as e:
            logger.error(f"שגיאה כללית ב-Pastebin: {e}")
            try:
                set_current_span_attributes({"status": "error", "error_signature": type(e).__name__})
            except Exception:
                pass
            return None
    
    @traced("integration.pastebin.get_content")
    async def get_paste_content(self, paste_id: str) -> Optional[str]:
        """קבלת תוכן paste"""
        
        try:
            raw_url = f"https://pastebin.com/raw/{paste_id}"
            from http_async import request as async_request
            async with async_request(
                "GET",
                raw_url,
                service="pastebin",
                endpoint="get_content",
            ) as response:
                    if response.status == 200:
                        content = await response.text()
                        logger.info(f"נשלף תוכן מ-Pastebin: {paste_id}")
                        return content
                    else:
                        logger.error(f"שגיאה בשליפת תוכן מ-Pastebin: {response.status}")
                        try:
                            set_current_span_attributes({"status": "error", "http.status_code": int(response.status)})
                        except Exception:
                            pass
                        return None
                        
        except Exception as e:
            logger.error(f"שגיאה בשליפת תוכן מ-Pastebin: {e}")
            try:
                set_current_span_attributes({"status": "error", "error_signature": type(e).__name__})
            except Exception:
                pass
            return None

class CodeSharingService:
    """שירות משולב לשיתוף קוד"""
    
    def __init__(self):
        # אין כאן ``GitHubGistIntegration``: Gist נוצר תמיד בשם משתמש מסוים,
        # דרך ``resolve_gist_for_user``. אינסטנס משותף כאן היה יוצר Gists של
        # כל המשתמשים תחת חשבון המערכת — בדיוק הבאג שהפרדה הזו סוגרת.
        self.pastebin = PastebinIntegration()
        self.internal_shares = {}  # לשיתוף פנימי בזיכרון (fallback)
    
    def get_available_services(self) -> List[str]:
        """קבלת רשימת שירותים זמינים (Gist לא כאן — הוא לכל משתמש בנפרד)"""
        services = []
        
        if self.pastebin.is_available():
            services.append("pastebin")
        
        services.append("internal")  # תמיד זמין
        
        return services
    
    @traced("integration.share_code")
    async def share_code(self, service: str, file_name: str, code: str, 
                        language: str, description: str = "", **kwargs) -> Optional[Dict[str, Any]]:
        """שיתוף קוד בשירות נבחר"""
        
        try:
            set_current_span_attributes({
                "service": str(service or ""),
                "language": str(language or ""),
                "file_name": str(file_name or ""),
            })
        except Exception:
            pass
        if service == "gist":
            # מסלול חסום בכוונה: השירות המשולב אינו מחזיק טוקן של משתמש,
            # ושיתוף Gist חייב לעבור דרך ``resolve_gist_for_user``.
            logger.error("share_code('gist') לא נתמך — יש להשתמש ב-resolve_gist_for_user")
            set_span_attrs_quietly({"status": "error", "reason": "gist_requires_user_token"})
            return None
        
        elif service == "pastebin" and self.pastebin.is_available():
            return await self.pastebin.create_paste(code, file_name, language, **kwargs)
        
        elif service == "internal":
            return self._create_internal_share(file_name, code, language, description)
        
        else:
            logger.error(f"שירות שיתוף לא זמין: {service}")
            try:
                set_current_span_attributes({"status": "error", "reason": "service_unavailable"})
            except Exception:
                pass
            return None
    
    def _create_internal_share(self, file_name: str, code: str, 
                              language: str, description: str) -> Dict[str, Any]:
        """יצירת שיתוף פנימי ושמירתו במסד נתונים (עם TTL),
        ונפילה לזיכרון אם ה-DB לא זמין."""

        share_id = secrets.token_urlsafe(12)
        now = datetime.now(timezone.utc)
        # ברירת מחדל: שבוע
        expires_at = now + timedelta(days=7)

        stored_ok = False
        try:
            from database import db as _db
            coll = _db.internal_shares_collection if hasattr(_db, 'internal_shares_collection') else None
            # DatabaseManager חושף collection דרך manager; גישה עקיפה:
            try:
                coll = _db.internal_shares_collection or _db.db.internal_shares
            except Exception:
                try:
                    coll = _db.db.internal_shares
                except Exception:
                    coll = None
            if coll is None:
                raise RuntimeError("internal_shares collection not available")

            doc = {
                "share_id": share_id,
                "file_name": file_name,
                "code": code,
                "language": language,
                "description": description,
                "created_at": now,
                "views": 0,
                "expires_at": expires_at,  # Date לשימוש ב-TTL
            }
            coll.insert_one(doc)
            stored_ok = True
        except Exception as e:
            logger.warning(f"DB not available for internal share; using memory store. Error: {e}")
            self.internal_shares[share_id] = {
                "id": share_id,
                "file_name": file_name,
                "code": code,
                "language": language,
                "description": description,
                "created_at": now.isoformat(),
                "views": 0,
                "expires_at": expires_at.isoformat(),
            }

        # בסיס URL: אם PUBLIC_BASE_URL לא קיים והוגדר WEBAPP_URL — השתמש בו.
        # שים לב: אם base מגיע בלי scheme (למשל "example.com"), טלגרם עלול לפתוח לינק כ-blank page.
        base = str((config.PUBLIC_BASE_URL or config.WEBAPP_URL or "") or "").strip()
        if base.endswith("/"):
            base = base[:-1]
        if base and "://" not in base:
            base = "https://" + base.lstrip("/")
        internal_url = f"{base}/share/{share_id}" if base else f"/share/{share_id}"

        result = {
            "id": share_id,
            "url": internal_url,
            "created_at": (now.isoformat()),
            "expires_at": expires_at.isoformat(),
            "service": "internal",
        }
        logger.info(f"נוצר שיתוף פנימי: {share_id} (stored_in_db={stored_ok})")
        return result
    
    def get_internal_share(self, share_id: str) -> Optional[Dict[str, Any]]:
        """קבלת שיתוף פנימי מה-DB (אם קיים), אחרת מזיכרון."""
        # קודם נסה DB
        try:
            from database import db as _db
            coll = None
            try:
                coll = _db.internal_shares_collection or _db.db.internal_shares
            except Exception:
                coll = _db.db.internal_shares
            if coll is not None:
                doc = coll.find_one({"share_id": share_id})
                if doc:
                    # TTL ימחק רשומות פגות, אז אם קיים — עדיין בתוקף
                    try:
                        coll.update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}})
                    except Exception:
                        pass
                    # החזר מבנה אחיד
                    return {
                        "id": doc.get("share_id"),
                        "file_name": doc.get("file_name"),
                        "code": doc.get("code"),
                        "language": doc.get("language"),
                        "description": doc.get("description"),
                        "created_at": (doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at")),
                        "expires_at": (doc.get("expires_at").isoformat() if isinstance(doc.get("expires_at"), datetime) else doc.get("expires_at")),
                        "views": int(doc.get("views") or 0),
                    }
        except Exception as e:
            logger.warning(f"DB get_internal_share failed; trying memory. Error: {e}")

        # נפילה לזיכרון
        share_data = self.internal_shares.get(share_id)
        if not share_data:
            return None
        # בדיקת תפוגה
        try:
            exp = share_data.get("expires_at")
            exp_dt = datetime.fromisoformat(exp) if isinstance(exp, str) else exp
            if datetime.now(timezone.utc) > exp_dt:
                try:
                    del self.internal_shares[share_id]
                except Exception:
                    pass
                return None
        except Exception:
            pass
        try:
            share_data["views"] = int(share_data.get("views", 0)) + 1
        except Exception:
            pass
        return share_data

class GitRepositoryIntegration:
    """אינטגרציה עם Git repositories (למשתמשים מתקדמים)"""
    
    def __init__(self):
        self.github = None
        token = _get_github_token()
        if token:
            try:
                self.github = Github(token)
            except Exception as e:
                logger.error(f"שגיאה בהתחברות ל-GitHub: {e}")
    
    def is_available(self) -> bool:
        """בדיקה אם האינטגרציה זמינה"""
        return self.github is not None
    
    def create_repository_file(self, repo_name: str, file_path: str, 
                              content: str, commit_message: str = None) -> Optional[Dict[str, Any]]:
        """יצירת קובץ ב-repository"""
        
        if not self.is_available():
            return None
        
        try:
            user = self.github.get_user()
            repo = user.get_repo(repo_name)
            
            if not commit_message:
                commit_message = f"Add {file_path}"
            
            # יצירת הקובץ
            result = repo.create_file(
                path=file_path,
                message=commit_message,
                content=content
            )
            
            return {
                "sha": result["commit"].sha,
                "url": result["content"].html_url,
                "download_url": result["content"].download_url,
                "commit_url": result["commit"].html_url
            }
            
        except Exception as e:
            logger.error(f"שגיאה ביצירת קובץ ב-repository: {e}")
            return None
    
    def get_user_repositories(self, limit: int = 50) -> List[Dict[str, Any]]:
        """קבלת repositories של המשתמש"""
        
        if not self.is_available():
            return []
        
        try:
            user = self.github.get_user()
            repos = []
            
            for repo in user.get_repos()[:limit]:
                repos.append({
                    "name": repo.name,
                    "full_name": repo.full_name,
                    "description": repo.description,
                    "url": repo.html_url,
                    "private": repo.private,
                    "language": repo.language,
                    "stars": repo.stargazers_count,
                    "forks": repo.forks_count,
                    "created_at": repo.created_at.isoformat(),
                    "updated_at": repo.updated_at.isoformat()
                })
            
            return repos
            
        except Exception as e:
            logger.error(f"שגיאה בקבלת repositories: {e}")
            return []

class WebhookIntegration:
    """אינטגרציה עם webhooks (להתראות ועדכונים)"""
    
    def __init__(self):
        self.webhooks = {}
    
    def register_webhook(self, user_id: int, webhook_url: str, 
                        events: List[str] = None) -> str:
        """רישום webhook"""
        
        if events is None:
            events = ["file_created", "file_updated", "file_deleted"]
        
        webhook_id = secrets.token_urlsafe(16)
        
        self.webhooks[webhook_id] = {
            "user_id": user_id,
            "url": webhook_url,
            "events": events,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "active": True
        }
        
        logger.info(f"נרשם webhook: {webhook_id} עבור משתמש {user_id}")
        return webhook_id
    
    async def trigger_webhook(self, user_id: int, event: str, data: Dict[str, Any]):
        """הפעלת webhook"""
        
        # מציאת webhooks רלוונטיים
        relevant_webhooks = [
            webhook for webhook in self.webhooks.values()
            if webhook["user_id"] == user_id and event in webhook["events"] and webhook["active"]
        ]
        
        if not relevant_webhooks:
            return
        
        # שליחת נתונים לכל webhook
        payload = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "data": data
        }
        
        from http_async import request as async_request
        for webhook in relevant_webhooks:
            try:
                async with async_request(
                    "POST",
                    webhook["url"],
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    service="webhook",
                    endpoint="trigger",
                ) as response:
                    if response.status == 200:
                        logger.info(f"Webhook נשלח בהצלחה: {webhook['url']}")
                    else:
                        logger.warning(f"Webhook החזיר שגיאה {response.status}: {webhook['url']}")
            except asyncio.TimeoutError:
                logger.warning(f"Webhook timeout: {webhook['url']}")
            except Exception as e:
                logger.error(f"שגיאה בשליחת webhook: {e}")


GIST_NEEDS_GITHUB_MESSAGE = (
    "🔗 כדי לשתף ב-Gist צריך לחבר את חשבון ה-GitHub שלך.\n\n"
    "ה-Gist ייווצר תחת החשבון שלך — כך הוא נשאר שלך ומופיע ברשימת ה-Gists שלך.\n\n"
    "לחיבור: תפריט ראשי ← 🔧 GitHub\n"
    "לחלופין אפשר לשתף דרך 📋 Pastebin, שלא דורש חיבור."
)

# תקלה טכנית היא לא "לא חיברת GitHub". משתמש מחובר שה-DB נפל לרגע אמור לראות
# "נסה שוב", לא הנחיה לחבר חשבון שכבר מחובר — ולכן שתי ההודעות נפרדות.
GIST_TEMPORARY_FAILURE_MESSAGE = (
    "❌ לא הצלחנו לגשת לחיבור ה-GitHub שלך כרגע. נסה שוב בעוד רגע."
)


class GistResolution(NamedTuple):
    """תוצאת ניסיון לבנות אינטגרציית Gist בשם משתמש.

    ``integration`` קיים רק כשהכול תקין. אחרת ``error_message`` מכיל את
    ההודעה שצריך להציג למשתמש — והיא שונה בין "לא חיברת" ל"תקלה זמנית".
    """

    integration: Optional["GitHubGistIntegration"]
    error_message: Optional[str]


def resolve_gist_for_user(user_id: int) -> GistResolution:
    """בונה אינטגרציית Gist שפועלת בשם המשתמש.

    ה-Gist נוצר תחת החשבון שהטוקן שייך לו. שימוש בטוקן הגלובלי היה יוצר
    את כל ה-Gists של כל המשתמשים תחת חשבון המערכת — ולכן כאן אין נפילה
    אליו בשום מסלול, גם לא בכשל.

    הקריאה חוסמת (DB + רשת), ולכן מתוך handler אסינכרוני יש לקרוא לה דרך
    ``asyncio.to_thread`` כדי לא לתקוע את ה-event loop.
    """
    if not user_id:
        return GistResolution(None, GIST_NEEDS_GITHUB_MESSAGE)
    try:
        from database import db as _db

        token = _db.get_github_token(int(user_id))
    except Exception:
        logger.exception("failed to load user github token for gist")
        return GistResolution(None, GIST_TEMPORARY_FAILURE_MESSAGE)
    if not token:
        return GistResolution(None, GIST_NEEDS_GITHUB_MESSAGE)
    try:
        integration = GitHubGistIntegration(token=token)
    except Exception:
        logger.exception("failed to build gist integration for user")
        return GistResolution(None, GIST_TEMPORARY_FAILURE_MESSAGE)
    if not integration.is_available():
        # יש טוקן שמור אבל ההתחברות נכשלה — טוקן פג/נשלל. זו לא תקלה זמנית,
        # והמשתמש צריך לחבר מחדש.
        return GistResolution(None, GIST_NEEDS_GITHUB_MESSAGE)
    return GistResolution(integration, None)


# יצירת אינסטנסים גלובליים. אין כאן ``gist_integration``: אינסטנס גלובלי היה
# נבנה עם הטוקן של המערכת, וכל שימוש בו היה יוצר Gist תחת חשבון הבוט —
# ל-Gist של משתמש יש להשתמש ב-``resolve_gist_for_user``.
pastebin_integration = PastebinIntegration()
code_sharing = CodeSharingService()
git_integration = GitRepositoryIntegration()
webhook_integration = WebhookIntegration()
