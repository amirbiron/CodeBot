"""
פקודות ChatOps לניהול Background Jobs.
"""

from typing import Optional

from services.job_orphan_reconciler import ORPHANED_FAILURE_REASON
from services.job_registry import JobRegistry, JobCategory
from services.job_tracker import get_job_tracker

_RUN_STATUS_ICONS = {
    "completed": "✅",
    "failed": "❌",
    "running": "🔄",
    "skipped": "⏭️",
}


def _run_icon(status: str, failure_reason: Optional[str]) -> str:
    """אייקון להרצה שהסתיימה — כלל אחד לכל הקוראים בקובץ.

    הרצה שנסגרה בפיוס נכתבת כ-``failed`` עם ``failure_reason``, ומקבלת 👻
    ולא ❌: ג'וב שנפל בקוד שלו והרצה שאיש לא סגר הן שתי אוכלוסיות שונות,
    ושתי הפקודות שמציגות הרצות חייבות לענות אותו דבר על אותה הרצה.
    """
    if status == "failed" and str(failure_reason or "").strip() == ORPHANED_FAILURE_REASON:
        return "👻"
    return _RUN_STATUS_ICONS.get(status, "❓")


def handle_jobs_command(args: str) -> str:
    """
    /jobs [category|status|<job_id>]

    דוגמאות:
    - /jobs               - רשימת כל ה-jobs
    - /jobs backup        - jobs בקטגוריית גיבויים
    - /jobs active        - הרצות פעילות
    - /jobs cache_warming - פרטי job ספציפי
    """
    args = args.strip().lower()
    registry = JobRegistry()
    tracker = get_job_tracker()

    # URL בסיס למוניטור (ניתן לקנפג דרך ENV)
    import os

    monitor_base_url = os.getenv("WEBAPP_URL", "https://your-app.onrender.com")

    # Active runs
    if args == "active":
        runs = tracker.get_active_runs()
        if not runs:
            return "✅ אין הרצות פעילות כרגע"

        lines = ["⚡ **הרצות פעילות:**\n"]
        for run in runs:
            status_icon = {"running": "🔄", "pending": "⏳"}.get(run.status.value, "❓")
            # 🔗 קישור ישיר ללוגים של ההרצה
            logs_link = f"{monitor_base_url}/jobs/monitor?run_id={run.run_id}"
            lines.append(
                f"{status_icon} `{run.job_id}` - {run.progress}% "
                f"({run.processed_items}/{run.total_items})\n"
                f"   [📋 לוגים]({logs_link})"
            )
        return "\n".join(lines)

    # Failed runs (recent)
    if args == "failed":
        try:
            coll = tracker.db.client[tracker.db.db_name]["job_runs"]  # type: ignore[attr-defined]
            cursor = coll.find({"status": "failed"}).sort("started_at", -1).limit(10)
            failed_docs = list(cursor)
        except Exception:
            return "❌ לא ניתן לשלוף כשלים אחרונים (DB לא זמין)"

        if not failed_docs:
            return "✅ אין כשלים אחרונים"

        def _safe_code(text: str, limit: int = 120) -> str:
            s = str(text or "").replace("`", "'").strip()
            if len(s) > limit:
                s = s[: max(0, limit - 1)] + "…"
            return s

        lines = ["❌ **כשלים אחרונים:**\n"]
        for doc in failed_docs:
            job_id = str(doc.get("job_id") or "").strip() or "unknown"
            run_id = str(doc.get("run_id") or "").strip()
            err = _safe_code(str(doc.get("error_message") or ""))
            try:
                started = doc.get("started_at")
                ts = started.strftime("%d/%m %H:%M") if started else ""
            except Exception:
                ts = ""
            logs_link = (
                f"{monitor_base_url}/jobs/monitor?run_id={run_id}" if run_id else f"{monitor_base_url}/jobs/monitor"
            )
            icon = _run_icon("failed", doc.get("failure_reason"))
            lines.append(f"{icon} `{job_id}` {ts}\n   `{err}`\n   [📋 לוגים]({logs_link})")

        return "\n".join(lines)

    # By category
    try:
        category = JobCategory(args)
        jobs = registry.list_by_category(category)
        if not jobs:
            return f"אין jobs בקטגוריה `{args}`"

        lines = [f"📋 **Jobs בקטגוריית {args}:**\n"]
        for job in jobs:
            status = "✅" if registry.is_enabled(job.job_id) else "❌"
            lines.append(f"{status} `{job.job_id}` - {job.name}")
        return "\n".join(lines)
    except ValueError:
        pass

    # Specific job
    if args:
        job = registry.get(args)
        if not job:
            return f"❌ Job `{args}` לא נמצא"

        history = tracker.get_job_history(args, limit=5)
        status = "✅ פעיל" if registry.is_enabled(args) else "❌ מושבת"

        lines = [
            f"📋 **{job.name}**\n",
            f"• מזהה: `{job.job_id}`",
            f"• סטטוס: {status}",
            f"• קטגוריה: {job.category.value}",
            f"• סוג: {job.job_type.value}",
        ]

        if job.interval_seconds:
            lines.append(f"• אינטרוול: {_format_interval(job.interval_seconds)}")

        if history:
            lines.append("\n**5 הרצות אחרונות:**")
            for run in history[:5]:
                icon = _run_icon(run.status.value, run.failure_reason)
                dur = ""
                if run.ended_at and run.started_at:
                    # אותו פורמט כמו שורת האינטרוול: הרצה שנסגרה בפיוס אחרי
                    # שבועות מוצגת בימים, ולא כמיליון שניות.
                    dur = f" ({_format_interval(int((run.ended_at - run.started_at).total_seconds()))})"

                line = f"  {icon} {run.started_at.strftime('%d/%m %H:%M')}{dur}"

                # 🔗 אם נכשל, הוסף קישור ללוגים
                if run.status.value == "failed":
                    logs_link = f"{monitor_base_url}/jobs/monitor?run_id={run.run_id}"
                    line += f"\n     └─ [📋 ראה לוגים]({logs_link})"

                lines.append(line)

        return "\n".join(lines)

    # All jobs summary
    jobs = registry.list_all()
    categories = {}
    for job in jobs:
        cat = job.category.value
        if cat not in categories:
            categories[cat] = []
        status = "✅" if registry.is_enabled(job.job_id) else "❌"
        categories[cat].append(f"{status} {job.name}")

    lines = ["🔄 **Background Jobs:**\n"]
    for cat, items in categories.items():
        icon = {
            "backup": "💾",
            "cache": "🗄️",
            "sync": "☁️",
            "cleanup": "🧹",
            "monitoring": "📊",
            "batch": "📦",
            "other": "📋",
        }.get(cat, "📋")
        lines.append(f"**{icon} {cat}:**")
        for item in items:
            lines.append(f"  {item}")
        lines.append("")

    lines.append("_השתמש ב-`/jobs active` לצפייה בהרצות פעילות_")
    lines.append("_השתמש ב-`/jobs failed` לצפייה בכשלים אחרונים_")
    return "\n".join(lines)


def _format_interval(seconds: int) -> str:
    if seconds >= 86400:
        return f"{seconds // 86400} ימים"
    if seconds >= 3600:
        return f"{seconds // 3600} שעות"
    if seconds >= 60:
        return f"{seconds // 60} דקות"
    return f"{seconds} שניות"
