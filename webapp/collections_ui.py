"""
Collections UI routes (server-rendered pages).
"""
from __future__ import annotations

from flask import Blueprint, render_template, redirect, session

collections_ui = Blueprint('collections_ui', __name__)


@collections_ui.route('/collections')
def collections_page():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('collections.html', default_collection_id=None)


@collections_ui.route('/collections/<collection_id>')
def collections_page_with_default(collection_id: str):
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('collections.html', default_collection_id=collection_id)


@collections_ui.route('/collections/shared/<token>')
def shared_collection_page(token: str):
    return render_template('collection_shared.html', share_token=token)
