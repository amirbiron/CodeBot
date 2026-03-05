"""
Sticky Notes Scope ID — פונקציה קנונית לחישוב scope_id.

מטרת הקובץ: למנוע שכפול לוגיקה בין webapp/services ולצמצם סיכון לסטיות עתידיות.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def make_scope_id(user_id: int, file_name: Optional[str]) -> Optional[str]:
    """Generate a stable scope_id for a user's file name.

    Must stay consistent with sticky notes routing logic.
    """
    if not file_name:
        return None
    try:
        normalized = re.sub(r"\s+", " ", str(file_name).strip()).lower()
    except Exception:
        normalized = str(file_name or "").strip().lower()
    if not normalized:
        return None
    digest = hashlib.sha256(f"{int(user_id)}::{normalized}".encode("utf-8")).hexdigest()[:16]
    return f"user:{int(user_id)}:file:{digest}"


def sync_sticky_notes_on_rename(
    db: Any,
    user_id: int,
    old_name: str,
    new_name: str,
    old_file_ids: Optional[List[str]] = None,
    new_file_id: str = '',
) -> None:
    """העברת פתקים דביקים מקובץ ישן לחדש לאחר שינוי שם.

    Parameters
    ----------
    db : pymongo database object
    user_id : מזהה משתמש
    old_name : שם הקובץ הישן
    new_name : שם הקובץ החדש
    old_file_ids : רשימת _id של מסמכים עם שם הקובץ הישן (אם ידועה)
    new_file_id : _id של המסמך החדש (אם רלוונטי, למשל בעריכה בווב)
    """
    if not old_name or not new_name or old_name == new_name:
        return
    coll = getattr(db, 'sticky_notes', None)
    if coll is None:
        return
    old_scope = make_scope_id(int(user_id), old_name)
    new_scope = make_scope_id(int(user_id), new_name)
    if not old_scope or not new_scope:
        return
    # אם לא סופקו file_ids ישנים, חפש אותם ב-DB
    if old_file_ids is None:
        old_file_ids = []
        try:
            snippets_coll = getattr(db, 'code_snippets', None)
            if snippets_coll is not None:
                old_file_ids = [
                    str(d['_id']) for d in
                    snippets_coll.find({'user_id': int(user_id), 'file_name': old_name}, {'_id': 1})
                    if d
                ]
        except Exception:
            pass
    match_criteria: list = [{'scope_id': old_scope}]
    if old_file_ids:
        match_criteria.append({'file_id': {'$in': old_file_ids}})
    query = {'user_id': int(user_id), '$or': match_criteria}
    update_fields: dict = {
        'scope_id': new_scope,
        'file_name': new_name,
        'updated_at': datetime.now(timezone.utc),
    }
    if new_file_id:
        update_fields['file_id'] = str(new_file_id)
    try:
        coll.update_many(query, {'$set': update_fields})
    except Exception as exc:
        try:
            logger.warning(
                "sticky notes rename sync failed",
                extra={"user_id": user_id, "old_name": old_name, "new_name": new_name, "error": str(exc)},
            )
        except Exception:
            pass

