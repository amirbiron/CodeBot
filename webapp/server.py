from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from bson import ObjectId
except Exception:  # pragma: no cover
    ObjectId = None  # type: ignore

try:
    # שימוש במנהל ה-DB הקיים של האפליקציה
    from database import db  # type: ignore
except Exception as e:  # pragma: no cover
    db = None  # type: ignore


app = FastAPI(title="CodeBot WebApp", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class BulkDeleteRequest(BaseModel):
    user_id: int
    ids: List[str]


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def _ensure_db() -> None:
    if db is None:
        raise HTTPException(status_code=500, detail="Database is not initialized")


def _filter_other_files(user_id: int) -> List[Dict[str, Any]]:
    """מחזיר רשימת 'שאר הקבצים' (ללא repo: וללא קבצים גדולים)."""
    _ensure_db()
    files = db.get_user_files(user_id, limit=10000) or []
    large_files, _ = db.get_user_large_files(user_id, page=1, per_page=10000)
    large_names = {lf.get("file_name") for lf in (large_files or []) if lf.get("file_name")}
    other: List[Dict[str, Any]] = []
    for f in files:
        name = f.get("file_name")
        tags = f.get("tags") or []
        if name and name not in large_names and not any(isinstance(t, str) and t.startswith("repo:") for t in tags):
            other.append(f)
    # מיין לפי עדכניות, אם קיים שדה
    other.sort(key=lambda d: d.get("updated_at") or d.get("created_at"), reverse=True)
    return other


@app.get("/api/files/other")
def list_other_files(
    user_id: int = Query(..., description="Telegram user id"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None),
) -> Dict[str, Any]:
    items = _filter_other_files(user_id)
    if q:
        ql = q.strip().lower()
        if ql:
            items = [it for it in items if ql in str(it.get("file_name", "")).lower()]
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]
    out_items = [
        {
            "id": str(it.get("_id")),
            "file_name": it.get("file_name"),
            "programming_language": it.get("programming_language"),
            "updated_at": it.get("updated_at"),
        }
        for it in page_items
    ]
    return {"items": out_items, "total": total, "page": page, "per_page": per_page}


@app.get("/api/files/by_repo")
def list_files_by_repo(
    user_id: int = Query(...),
    repo_tag: str = Query(..., description="Tag in form repo:owner/name"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    _ensure_db()
    items, total = db.get_user_files_by_repo(user_id, repo_tag, page=page, per_page=per_page)
    out_items = [
        {
            "id": str(it.get("_id")),
            "file_name": it.get("file_name"),
            "programming_language": it.get("programming_language"),
            "updated_at": it.get("updated_at"),
        }
        for it in items
    ]
    return {"items": out_items, "total": int(total or 0), "page": page, "per_page": per_page}


@app.post("/api/files/bulk_delete")
def bulk_delete(req: BulkDeleteRequest = Body(...)) -> Dict[str, Any]:
    _ensure_db()
    if not req.ids:
        return {"deleted": 0}
    if ObjectId is None:
        raise HTTPException(status_code=500, detail="BSON ObjectId not available")
    try:
        ids = [ObjectId(i) for i in req.ids]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ids")
    docs = list(db.collection.find({"_id": {"$in": ids}, "user_id": req.user_id}))
    names = [d.get("file_name") for d in docs if d.get("file_name")]
    deleted = db.soft_delete_files_by_names(req.user_id, names)
    return {"deleted": int(deleted or 0)}


# הגשת סטטיק (index.html וכו')
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")

