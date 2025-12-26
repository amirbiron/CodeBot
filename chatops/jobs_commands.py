# chatops/jobs_commands.py
"""
פקודות ChatOps לניהול Background Jobs.
"""

import os
from typing import Dict, List
from services.job_registry import JobRegistry, JobCategory
from services.job_tracker import get_job_tracker


def handle_jobs_command(args: str) -> str:
    """
    /jobs [category|status|<job_id>]

    דוגמאות:
    - /jobs               - רשימת כל ה-jobs
    - /jobs backup        - jobs בקטגוריית גיבויים
    - /jobs active        - הרצות פעילות
    - /jobs failed        - הרצות שנכשלו לאחרונה
    - /jobs cache_warming - פרטי job ספציפי
    """
    args = args.strip().lower()
    registry = JobRegistry()
    tracker = get_job_tracker()

    # URL בסיס למוניטור (ניתן לקנפג דרך ENV)
    monitor_base_url = os.getenv("WEBAPP_URL", "http://localhost")

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

    # Failed runs
    if args == "failed":
        runs = tracker.get_failed_runs(limit=10)
        if not runs:
            return "✅ אין הרצות שנכשלו לאחרונה"

        lines = ["❌ **הרצות שנכשלו:**\n"]
        for run in runs:
            time_str = run.ended_at.strftime('%d/%m %H:%M') if run.ended_at else "-"
            error_short = (run.error_message[:50] + "...") if run.error_message and len(run.error_message) > 50 else (run.error_message or "")
            logs_link = f"{monitor_base_url}/jobs/monitor?run_id={run.run_id}"
            lines.append(
                f"❌ `{run.job_id}` - {time_str}\n"
                f"   {error_short}\n"
                f"   [📋 ראה לוגים]({logs_link})"
            )
        return "\n".join(lines)

    # By category
    try:
        category = JobCategory(args)
        jobs = registry.list_by_category(category)
        if not jobs:
            return f"אין jobs בקטגוריה `{args}`"

        lines = [f"📋 **Jobs בקטגוריית {args}:**\n"]
        for j in jobs:
            status = "✅" if registry.is_enabled(j.job_id) else "❌"
            lines.append(f"{status} `{j.job_id}` - {j.name}")
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
                icon = {
                    "completed": "✅", "failed": "❌",
                    "running": "🔄", "skipped": "⏭️"
                }.get(run.status.value, "❓")
                dur = ""
                if run.ended_at and run.started_at:
                    dur = f" ({(run.ended_at - run.started_at).total_seconds():.1f}s)"

                line = f"  {icon} {run.started_at.strftime('%d/%m %H:%M')}{dur}"

                # 🔗 אם נכשל, הוסף קישור ללוגים
                if run.status.value == "failed":
                    logs_link = f"{monitor_base_url}/jobs/monitor?run_id={run.run_id}"
                    line += f"\n     └─ [📋 ראה לוגים]({logs_link})"

                lines.append(line)

        return "\n".join(lines)

    # All jobs summary
    jobs = registry.list_all()
    if not jobs:
        return "📋 אין jobs רשומים במערכת"

    categories: Dict[str, List[str]] = {}
    for job in jobs:
        cat = job.category.value
        if cat not in categories:
            categories[cat] = []
        status = "✅" if registry.is_enabled(job.job_id) else "❌"
        categories[cat].append(f"{status} {job.name}")

    lines = ["🔄 **Background Jobs:**\n"]
    for cat, items in categories.items():
        icon = {
            "backup": "💾", "cache": "🗄️", "sync": "☁️", "cleanup": "🧹",
            "monitoring": "📊", "batch": "📦", "other": "📋"
        }.get(cat, "📋")
        lines.append(f"**{icon} {cat}:**")
        for item in items:
            lines.append(f"  {item}")
        lines.append("")

    lines.append("_השתמש ב-`/jobs active` לצפייה בהרצות פעילות_")
    lines.append("_השתמש ב-`/jobs failed` לצפייה בשגיאות אחרונות_")
    return "\n".join(lines)


def _format_interval(seconds: int) -> str:
    if seconds >= 86400:
        return f"{seconds // 86400} ימים"
    if seconds >= 3600:
        return f"{seconds // 3600} שעות"
    if seconds >= 60:
        return f"{seconds // 60} דקות"
    return f"{seconds} שניות"
