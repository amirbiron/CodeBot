from __future__ import annotations

import asyncio
import hmac
import logging
import os
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional, Union

from aiohttp import web

# הערה: השירות (``QueryProfilerService``) סינכרוני לגמרי — קריאות pymongo רגילות.
# ה-handlers כאן הם aiohttp ורצים בתוך event loop אמיתי, ולכן הם עוטפים ב-``asyncio.to_thread``
# כדי לא לחסום אותו. זה ההפך מהדפוס שהוסר מה-WebApp: שם קוד *סינכרוני* ניסה להריץ לולאה.
# מכאן, מלולאה אמיתית, ``to_thread`` הוא הכיוון הנכון — אותו מבנה כמו
# ``ThreadPoolDatabaseHealthService`` ב-services/db_health_service.py.

from services.query_profiler_service import (
    AggregationExplainPlan,
    ExplainPlan,
    QueryProfilerService,
    RateLimiter,
)
from services.query_profiler_service import ExplainTimeoutError as _ProfilerExplainTimeout
from services.query_profiler_service import ProfilerInputError as _ProfilerInputError

logger = logging.getLogger(__name__)


def require_profiler_auth(handler):
    """
    Middleware לאימות גישה לפרופיילר.

    אפשרויות:
    1. Token באמצעות header
    2. הגבלת IP
    """

    @wraps(handler)
    async def wrapper(request: web.Request) -> web.Response:
        # Rate limiting (best-effort)
        try:
            limit = int(os.environ.get("PROFILER_RATE_LIMIT", "60"))
        except Exception:
            limit = 60
        limiter = request.app.get("_profiler_rate_limiter")
        if limiter is None:
            limiter = RateLimiter(requests_per_minute=limit)
            request.app["_profiler_rate_limiter"] = limiter
        client_id = request.headers.get("X-Profiler-Client", "") or request.remote or "unknown"
        if isinstance(limiter, RateLimiter) and not limiter.is_allowed(str(client_id)):
            return web.json_response({"status": "error", "message": "rate_limited"}, status=429)

        # בדיקת token
        auth_token = os.environ.get("PROFILER_AUTH_TOKEN")
        if auth_token:
            provided_token = request.headers.get("X-Profiler-Token", "")
            if not hmac.compare_digest(str(provided_token or ""), str(auth_token or "")):
                return web.json_response({"status": "error", "message": "Unauthorized"}, status=401)

        # הגבלת IP (אופציונלי)
        allowed_ips_raw = os.environ.get("PROFILER_ALLOWED_IPS", "")
        allowed_ips = [ip.strip() for ip in str(allowed_ips_raw or "").split(",") if ip.strip()]
        if allowed_ips:  # רק אם מוגדר
            client_ip = request.remote
            if client_ip not in allowed_ips:
                return web.json_response({"status": "error", "message": "IP not allowed"}, status=403)

        return await handler(request)

    return wrapper


#: הודעות למשתמש לפי ``error_code``. ההודעה של ``BROKEN_QUERY_SHAPE`` נשמרת
#: מילה במילה מהגרסה הקודמת, כדי לא לשנות התנהגות קיימת.
#: ⚠️ חייבת להישאר זהה לזו שב-``webapp/app.py``, ולכסות כל ``error_code``
#: שהשירות מגדיר. שני הדברים נאכפים בטסטים.
_PROFILER_INPUT_MESSAGES = {
    "PROFILER_INPUT_ERROR": "הבקשה לפרופיילר אינה תקינה.",
    "BROKEN_QUERY_SHAPE": "השאילתה מכילה נרמול שבור מגרסה ישנה. יש להשתמש בשאילתה המקורית או להקליט מחדש.",
    "INVALID_VERBOSITY": "רמת פירוט לא נתמכת ל-explain. בחר queryPlanner, executionStats או allPlansExecution.",
}

#: ראו ההסבר המקביל ב-``webapp/app.py``: לא ``str(exc)``.
_PROFILER_INPUT_FALLBACK_MESSAGE = "הבקשה לפרופיילר אינה תקינה."

#: מדיניות ה-timeout, זהה ל-``webapp/app.py``.
_PROFILER_TIMEOUT_MESSAGE = (
    "ה-explain חרג ממגבלת הזמן. נסה שוב עם queryPlanner, או הגדל את PROFILER_EXPLAIN_MAX_TIME_MS."
)
_PROFILER_TIMEOUT_STATUS = 504


def _profiler_input_error_payload(exc) -> dict:
    code = str(getattr(exc, "error_code", "") or "PROFILER_INPUT_ERROR")
    message = _PROFILER_INPUT_MESSAGES.get(code)
    if message is None:
        logger.warning(
            "profiler_input_error_without_message",
            extra={"error_code": code, "error": str(exc)},
        )
        message = _PROFILER_INPUT_FALLBACK_MESSAGE
    return {"status": "error", "message": message, "error_code": code}


def setup_profiler_routes(app: web.Application, profiler_service: QueryProfilerService):
    """הגדרת routes לפרופיילר"""

    @require_profiler_auth
    async def get_slow_queries(request: web.Request) -> web.Response:
        """GET /api/profiler/slow-queries"""
        try:
            limit = int(request.query.get("limit", 50))
        except Exception:
            limit = 50
        collection = request.query.get("collection")
        min_time = request.query.get("min_time")
        hours = request.query.get("hours")

        since = None
        if hours:
            try:
                since = datetime.utcnow() - timedelta(hours=int(hours))
            except Exception:
                since = None

        min_time_ms = None
        if min_time:
            try:
                min_time_ms = float(min_time)
            except Exception:
                min_time_ms = None

        queries = await asyncio.to_thread(
            profiler_service.get_slow_queries,
            limit=limit,
            collection_filter=collection,
            min_execution_time_ms=min_time_ms,
            since=since,
        )

        return web.json_response(
            {"status": "success", "data": [_serialize_slow_query(q) for q in queries], "count": len(queries)}
        )

    @require_profiler_auth
    async def get_explain_plan(request: web.Request) -> web.Response:
        """POST /api/profiler/explain"""
        body = await request.json()

        collection = body.get("collection")
        query = body.get("query", {})
        pipeline = body.get("pipeline")
        verbosity = body.get("verbosity", "queryPlanner")

        if not collection:
            return web.json_response({"status": "error", "message": "collection is required"}, status=400)

        try:
            # תומך גם ב-aggregation pipelines
            if isinstance(pipeline, list):
                explain = await asyncio.to_thread(
                    profiler_service.get_aggregation_explain,
                    collection=collection, pipeline=pipeline, verbosity=verbosity
                )
                return web.json_response({"status": "success", "data": _serialize_aggregation_explain(explain)})

            explain = await asyncio.to_thread(
                profiler_service.get_explain_plan, collection=collection, query=query, verbosity=verbosity
            )
            return web.json_response({"status": "success", "data": _serialize_explain_plan(explain)})
        except _ProfilerExplainTimeout as e:
            logger.warning("profiler_explain_timeout", extra={"error": str(e)})
            return web.json_response({
                "status": "error",
                "message": _PROFILER_TIMEOUT_MESSAGE,
                "error_code": "EXPLAIN_TIMEOUT"
            }, status=_PROFILER_TIMEOUT_STATUS)
        except _ProfilerInputError as e:
            # לפי טיפוס ולא לפי טקסט ההודעה: קודם רק "broken array normalization"
            # זוהה כשגיאת קלט, וכל ולידציה חדשה נפלה ל-raise ומשם ל-500.
            return web.json_response(_profiler_input_error_payload(e), status=400)

    @require_profiler_auth
    async def get_recommendations(request: web.Request) -> web.Response:
        """POST /api/profiler/recommendations"""
        body = await request.json()

        collection = body.get("collection")
        query = body.get("query", {})
        pipeline = body.get("pipeline")

        if not collection:
            return web.json_response({"status": "error", "message": "collection is required"}, status=400)

        try:
            if isinstance(pipeline, list):
                explain = await asyncio.to_thread(
                    profiler_service.get_aggregation_explain, collection=collection, pipeline=pipeline
                )
                recommendations = profiler_service.analyze_aggregation_and_recommend(explain)
                return web.json_response(
                    {
                        "status": "success",
                        "data": {
                            "aggregation_explain": _serialize_aggregation_explain(explain),
                            "recommendations": [_serialize_recommendation(r) for r in recommendations],
                        },
                    }
                )

            explain = await asyncio.to_thread(
                profiler_service.get_explain_plan, collection=collection, query=query
            )
            recommendations = profiler_service.generate_recommendations(explain)

            return web.json_response(
                {
                    "status": "success",
                    "data": {
                        "explain": _serialize_explain_plan(explain),
                        "recommendations": [_serialize_recommendation(r) for r in recommendations],
                    },
                }
            )
        except _ProfilerExplainTimeout as e:
            logger.warning("profiler_explain_timeout", extra={"error": str(e)})
            return web.json_response({
                "status": "error",
                "message": _PROFILER_TIMEOUT_MESSAGE,
                "error_code": "EXPLAIN_TIMEOUT"
            }, status=_PROFILER_TIMEOUT_STATUS)
        except _ProfilerInputError as e:
            # לפי טיפוס ולא לפי טקסט ההודעה: קודם רק "broken array normalization"
            # זוהה כשגיאת קלט, וכל ולידציה חדשה נפלה ל-raise ומשם ל-500.
            return web.json_response(_profiler_input_error_payload(e), status=400)

    @require_profiler_auth
    async def get_summary(request: web.Request) -> web.Response:
        """GET /api/profiler/summary"""
        summary = await asyncio.to_thread(profiler_service.get_summary)
        return web.json_response({"status": "success", "data": summary})

    @require_profiler_auth
    async def get_collection_stats(request: web.Request) -> web.Response:
        """GET /api/profiler/collection/{name}/stats"""
        collection = request.match_info["name"]
        stats = await asyncio.to_thread(profiler_service.get_collection_stats, collection)
        return web.json_response({"status": "success", "data": stats})

    # רישום routes
    app.router.add_get("/api/profiler/slow-queries", get_slow_queries)
    app.router.add_post("/api/profiler/explain", get_explain_plan)
    app.router.add_post("/api/profiler/recommendations", get_recommendations)
    # Alias 1:1 למדריך (חלק מהתרשימים משתמשים בשם analyze)
    app.router.add_post("/api/profiler/analyze", get_recommendations)
    app.router.add_get("/api/profiler/summary", get_summary)
    app.router.add_get("/api/profiler/collection/{name}/stats", get_collection_stats)


def _serialize_slow_query(query) -> Dict[str, Any]:
    """המרת SlowQueryRecord ל-dict"""
    return {
        "query_id": query.query_id,
        "collection": query.collection,
        "operation": query.operation,
        "query_shape": query.query_shape,
        "execution_time_ms": query.execution_time_ms,
        "timestamp": query.timestamp.isoformat(),
    }


def _serialize_explain_plan(plan: ExplainPlan) -> Dict[str, Any]:
    """המרת ExplainPlan ל-dict"""
    return {
        "query_id": plan.query_id,
        "collection": plan.collection,
        "query_shape": plan.query_shape,
        "winning_plan": _serialize_stage(plan.winning_plan),
        "rejected_plans": [_serialize_stage(p) for p in plan.rejected_plans],
        "stats": {
            "execution_time_ms": plan.stats.execution_time_ms,
            "docs_examined": plan.stats.docs_examined,
            "docs_returned": plan.stats.docs_returned,
            "keys_examined": plan.stats.keys_examined,
            "index_used": plan.stats.index_used,
            "is_covered_query": plan.stats.is_covered_query,
            "efficiency_ratio": round(plan.stats.efficiency_ratio, 4),
        }
        if plan.stats
        else None,
        "timestamp": plan.timestamp.isoformat(),
    }


def _serialize_stage(stage) -> Dict[str, Any]:
    """המרת ExplainStage ל-dict"""
    return {
        "stage": stage.stage.value,
        "index_name": stage.index_name,
        "direction": stage.direction,
        "filter_condition": stage.filter_condition,
        "input_stage": _serialize_stage(stage.input_stage) if stage.input_stage else None,
        "children": [_serialize_stage(c) for c in stage.children],
    }


def _serialize_aggregation_explain(plan: AggregationExplainPlan) -> Dict[str, Any]:
    return {
        "query_id": plan.query_id,
        "collection": plan.collection,
        "pipeline_shape": plan.pipeline_shape,
        "stages": [
            {
                "stage_name": s.stage_name,
                "execution_time_ms": s.execution_time_ms,
                "docs_examined": s.docs_examined,
                "n_returned": s.n_returned,
                "uses_disk": s.uses_disk,
                "memory_usage_bytes": s.memory_usage_bytes,
                "index_used": s.index_used,
                "lookup_collection": s.lookup_collection,
                "lookup_strategy": s.lookup_strategy,
            }
            for s in plan.stages
        ],
        "total_execution_time_ms": plan.total_execution_time_ms,
        "timestamp": plan.timestamp.isoformat(),
    }


def _serialize_recommendation(rec) -> Dict[str, Any]:
    """המרת OptimizationRecommendation ל-dict"""
    return {
        "id": rec.id,
        "title": rec.title,
        "description": rec.description,
        "severity": rec.severity.value,
        "category": rec.category,
        "suggested_action": rec.suggested_action,
        "estimated_improvement": rec.estimated_improvement,
        "code_example": rec.code_example,
        "documentation_link": rec.documentation_link,
    }

