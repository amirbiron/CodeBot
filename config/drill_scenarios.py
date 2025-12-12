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
}

