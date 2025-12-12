"""
תרחישי Drill Mode (תרגול) מוגדרים מראש.

עקרונות:
- כל תרגול חייב לכלול metadata.is_drill = True
- הכותרת צריכה להתחיל ב-🎭 כדי לבלוט בכל UI/טלגרם
- ניתן להשתמש ב-Templating פשוט בשדות metadata (למשל {{current_timestamp}})
"""

from __future__ import annotations

DRILL_SCENARIOS = {
    "latency_spike": {
        "alert_type": "slow_response",
        "severity": "warning",
        "title": "🎭 DRILL: Latency Spike Detected",
        "message": "P95 response time jumped to 850ms (baseline: 200ms)",
        "metadata": {
            "is_drill": True,
            "scenario": "latency_spike",
            "p95_latency": "850ms",
            "baseline": "200ms",
            "timestamp": "{{current_timestamp}}",
        },
    },
    "error_storm": {
        "alert_type": "high_error_rate",
        "severity": "critical",
        "title": "🎭 DRILL: High Error Rate",
        "message": "Error rate: 15% (150 errors in last 5 minutes)",
        "metadata": {
            "is_drill": True,
            "scenario": "error_storm",
            "error_rate": "15%",
            "error_count": 150,
            "timeframe": "5m",
            "timestamp": "{{current_timestamp}}",
        },
    },
    "db_connection_issue": {
        "alert_type": "db_connection_issue",
        "severity": "critical",
        "title": "🎭 DRILL: Database Connection Failed",
        "message": "MongoDB connection pool exhausted (50/50 connections)",
        "metadata": {
            "is_drill": True,
            "scenario": "db_connection_issue",
            "pool_size": 50,
            "active_connections": 50,
            "timestamp": "{{current_timestamp}}",
        },
    },
    "deployment_event": {
        "alert_type": "deployment_event",
        "severity": "info",
        "title": "🎭 DRILL: Deployment Completed",
        "message": "Version v2.5.0 deployed to production",
        "metadata": {
            "is_drill": True,
            "scenario": "deployment_event",
            "version": "v2.5.0",
            "environment": "production",
            "timestamp": "{{current_timestamp}}",
        },
    },
    "rate_limit_warning": {
        "alert_type": "rate_limit_warning",
        "severity": "warning",
        "title": "🎭 DRILL: GitHub Rate Limit Warning",
        "message": "GitHub API rate limit: 100/5000 remaining",
        "metadata": {
            "is_drill": True,
            "scenario": "rate_limit_warning",
            "remaining": 100,
            "limit": 5000,
            "timestamp": "{{current_timestamp}}",
        },
    },
    "unknown_alert": {
        # לא קיים במערכת! מיועד לבדוק fallback של Runbook/UX
        "alert_type": "zombie_apocalypse_warning",
        "severity": "warning",
        "title": "🎭 DRILL: Unknown Alert Type",
        "message": "Testing fallback Runbook handling for unrecognized alert types",
        "metadata": {
            "is_drill": True,
            "scenario": "unknown_alert",
            "purpose": "fallback_test",
            "timestamp": "{{current_timestamp}}",
        },
    },
    "resource_critical": {
        "alert_type": "resource_exhaustion",
        "severity": "critical",
        "title": "🎭 DRILL: צריכת משאבים קריטית",
        "message": "CPU: 95%, RAM: 7.8GB/8GB (98%), Disk: 92%",
        "metadata": {
            "is_drill": True,
            "scenario": "resource_critical",
            "cpu_percent": 95,
            "ram_used_gb": 7.8,
            "ram_total_gb": 8.0,
            "ram_percent": 98,
            "disk_percent": 92,
            "timestamp": "{{current_timestamp}}",
        },
    },
    "queue_backlog": {
        "alert_type": "queue_backlog",
        "severity": "warning",
        "title": "🎭 DRILL: עיכוב בעיבוד משימות רקע",
        "message": "Queue: 5000 משימות ממתינות, Worker תקוע/איטי",
        "metadata": {
            "is_drill": True,
            "scenario": "queue_backlog",
            "pending_tasks": 5000,
            "queue_name": "celery",
            "oldest_task_age": "45m",
            "worker_status": "slow",
            "timestamp": "{{current_timestamp}}",
        },
    },
    "external_service_failure": {
        "alert_type": "external_service_down",
        "severity": "warning",
        "title": "🎭 DRILL: כשל בשירות חיצוני",
        "message": "GitHub API לא זמין - Timeout אחרי 30 שניות",
        "metadata": {
            "is_drill": True,
            "scenario": "external_service",
            "service_name": "GitHub API",
            "error_type": "timeout",
            "timeout_seconds": 30,
            "timestamp": "{{current_timestamp}}",
        },
    },
}

