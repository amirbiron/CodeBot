"""
GitHub Issue Action Handler
===========================
פותח Issues אוטומטיים ב-GitHub כאשר כלל מתאים.
"""

import os
import logging
import aiohttp
from typing import Any, Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# הגדרות
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "owner/repo")  # לדוגמה: "amirbiron/CodeBot"
GITHUB_API_URL = "https://api.github.com"


class GitHubIssueAction:
    """
    Handler ליצירת GitHub Issues.

    דוגמת שימוש בכלל:
    ```json
    {
        "type": "create_github_issue",
        "labels": ["auto-generated", "bug"],
        "assignees": ["username"],
        "title_template": "🐛 [Auto] {{error_type}}: {{error_message}}",
        "body_template": "..."
    }
    ```
    """

    def __init__(self, token: str = GITHUB_TOKEN, repo: str = GITHUB_REPO):
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }

    async def execute(
        self,
        action_config: Dict[str, Any],
        alert_data: Dict[str, Any],
        triggered_conditions: list,
    ) -> Dict[str, Any]:
        """
        מבצע את הפעולה - פותח Issue ב-GitHub.

        Args:
            action_config: הגדרות הפעולה מהכלל
            alert_data: נתוני ההתראה/שגיאה
            triggered_conditions: התנאים שהופעלו

        Returns:
            dict עם תוצאת הפעולה (issue_url, issue_number, וכו')
        """
        if not self.token:
            logger.error("GitHub token not configured")
            return {"success": False, "error": "GitHub token not configured"}

        # בניית כותרת (עם קיצור - כותרות GitHub מוגבלות)
        title = self._render_template(
            action_config.get("title_template", "🐛 [Auto] New Error: {{error_message}}"),
            alert_data,
            truncate_long_values=True,  # קיצור רק בכותרת
            max_length=80,
        )

        # בניית גוף ה-Issue
        body = self._build_issue_body(action_config, alert_data, triggered_conditions)

        # Labels
        labels = action_config.get("labels", ["auto-generated", "bug"])

        # Assignees
        assignees = action_config.get("assignees", [])

        # בדיקה אם כבר קיים Issue פתוח לשגיאה זו
        error_signature = alert_data.get("error_signature", "")
        if error_signature:
            existing = await self._find_existing_issue(error_signature)
            if existing:
                logger.info(
                    f"Issue already exists for error {error_signature}: #{existing['number']}"
                )
                # עדכון ה-Issue הקיים עם הופעה חדשה
                await self._add_occurrence_comment(existing["number"], alert_data)
                return {
                    "success": True,
                    "action": "updated_existing",
                    "issue_number": existing["number"],
                    "issue_url": existing["html_url"],
                }

        # יצירת Issue חדש
        issue_data = {
            "title": title[:256],  # GitHub limit
            "body": body,
            "labels": labels,
        }

        if assignees:
            issue_data["assignees"] = assignees

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GITHUB_API_URL}/repos/{self.repo}/issues"
                async with session.post(url, json=issue_data, headers=self.headers) as resp:
                    if resp.status == 201:
                        result = await resp.json()
                        logger.info(
                            f"Created GitHub issue #{result['number']}: {result['html_url']}"
                        )
                        return {
                            "success": True,
                            "action": "created",
                            "issue_number": result["number"],
                            "issue_url": result["html_url"],
                        }
                    error_text = await resp.text()
                    logger.error(f"Failed to create issue: {resp.status} - {error_text}")
                    return {"success": False, "error": error_text}

        except Exception as e:
            logger.error(f"Error creating GitHub issue: {e}")
            return {"success": False, "error": str(e)}

    def _render_template(
        self,
        template: str,
        data: Dict[str, Any],
        truncate_long_values: bool = False,
        max_length: int = 100,
    ) -> str:
        """
        מחליף placeholders בתבנית.

        Args:
            template: תבנית עם {{placeholders}}
            data: מילון ערכים
            truncate_long_values: האם לקצר ערכים ארוכים (לכותרות בלבד)
            max_length: אורך מקסימלי כשמקצרים
        """
        result = template
        for key, value in data.items():
            placeholder = "{{" + key + "}}"
            if placeholder in result:
                str_value = str(value)
                # קיצור רק אם התבקש במפורש (לכותרות)
                if truncate_long_values and len(str_value) > max_length:
                    str_value = str_value[: max_length - 3] + "..."
                result = result.replace(placeholder, str_value)
        return result

    def _build_issue_body(
        self,
        action_config: Dict[str, Any],
        alert_data: Dict[str, Any],
        triggered_conditions: list,
    ) -> str:
        """בונה את גוף ה-Issue בפורמט Markdown."""

        # תבנית ברירת מחדל
        default_template = """## 🐛 שגיאה אוטומטית

> Issue זה נוצר אוטומטית על ידי מערכת הניטור.

### פרטי השגיאה

| שדה | ערך |
|-----|-----|
| **סוג** | `{{alert_type}}` |
| **שירות** | `{{service_name}}` |
| **סביבה** | `{{environment}}` |
| **זמן** | {{timestamp}} |
| **חתימה** | `{{error_signature}}` |

### הודעת השגיאה

```
{{error_message}}
```

### Stack Trace

<details>
<summary>לחץ להרחבה</summary>

```
{{stack_trace}}
```

</details>

### תנאים שהופעלו

{{triggered_conditions_list}}

### מידע נוסף

- **Error Rate:** {{error_rate}}%
- **Latency:** {{latency_avg_ms}}ms
- **מספר הופעות:** {{occurrence_count}}

---

<sub>🤖 נוצר אוטומטית ע"י Visual Rule Engine | כלל: `{{rule_name}}`</sub>
"""

        template = action_config.get("body_template", default_template)

        # הוספת רשימת תנאים
        conditions_list = "\n".join([f"- ✅ `{c}`" for c in triggered_conditions])
        alert_data["triggered_conditions_list"] = conditions_list or "- (אין תנאים)"

        # הוספת timestamp
        alert_data["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # רינדור התבנית
        body = self._render_template(template, alert_data)

        # הגבלת אורך
        if len(body) > 65000:  # GitHub limit ~65535
            body = body[:64000] + "\n\n...(truncated)"

        return body

    async def _find_existing_issue(self, error_signature: str) -> Optional[Dict[str, Any]]:
        """מחפש Issue קיים פתוח עם אותה חתימת שגיאה.

        🔧 תיקון באג: URL encoding נכון של search query.
        """
        try:
            # 🔧 תיקון: שימוש ב-urllib.parse.quote לקידוד נכון של ה-query
            from urllib.parse import quote

            async with aiohttp.ClientSession() as session:
                # חיפוש ב-Issues פתוחים
                search_query = f"repo:{self.repo} is:issue is:open in:body {error_signature}"
                # קידוד נכון של ה-query string
                encoded_query = quote(search_query, safe="")
                url = f"{GITHUB_API_URL}/search/issues?q={encoded_query}"

                async with session.get(url, headers=self.headers) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("total_count", 0) > 0:
                            return result["items"][0]
            return None
        except Exception as e:
            logger.warning(f"Error searching for existing issue: {e}")
            return None

    async def _add_occurrence_comment(self, issue_number: int, alert_data: Dict[str, Any]) -> None:
        """מוסיף תגובה ל-Issue קיים על הופעה נוספת."""
        comment_body = f"""### 🔄 הופעה נוספת

| שדה | ערך |
|-----|-----|
| **זמן** | {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")} |
| **Error Rate** | {alert_data.get("error_rate", "N/A")}% |
| **סה\"כ הופעות** | {alert_data.get("occurrence_count", "N/A")} |
"""

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GITHUB_API_URL}/repos/{self.repo}/issues/{issue_number}/comments"
                async with session.post(url, json={"body": comment_body}, headers=self.headers) as resp:
                    if resp.status == 201:
                        logger.info(f"Added occurrence comment to issue #{issue_number}")
        except Exception as e:
            logger.warning(f"Failed to add comment to issue #{issue_number}: {e}")


# =============================================================================
# רישום ה-Action במנוע
# =============================================================================


def register_github_action(engine):
    """רושם את ה-action במנוע הכללים."""
    handler = GitHubIssueAction()
    engine.register_action_handler("create_github_issue", handler.execute)

