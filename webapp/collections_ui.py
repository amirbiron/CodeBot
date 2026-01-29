"""
Collections UI routes (server-rendered pages).
"""
from __future__ import annotations

import os

from flask import Blueprint, render_template, redirect, session

try:
    from config import config as _cfg  # type: ignore
except Exception:  # pragma: no cover
    _cfg = None  # type: ignore

collections_ui = Blueprint('collections_ui', __name__)

def _tags_feature_enabled() -> bool:
    try:
        env_val = os.getenv("FEATURE_COLLECTIONS_TAGS")
        if env_val is not None:
            return str(env_val or "").strip().lower() in {"1", "true", "yes", "y", "on"}
    except Exception:
        pass
    try:
        if _cfg is None:
            return True
        return bool(getattr(_cfg, "FEATURE_COLLECTIONS_TAGS", True))
    except Exception:
        return True


@collections_ui.route('/collections')
def collections_page():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template(
        'collections.html',
        default_collection_id=None,
        tags_enabled=_tags_feature_enabled(),
    )


@collections_ui.route('/collections/<collection_id>')
def collections_page_with_default(collection_id: str):
    if 'user_id' not in session:
        return redirect('/login')
    return render_template(
        'collections.html',
        default_collection_id=collection_id,
        tags_enabled=_tags_feature_enabled(),
    )


@collections_ui.route('/collections/shared/<token>')
def shared_collection_page(token: str):
    return render_template('collection_shared.html', share_token=token)
