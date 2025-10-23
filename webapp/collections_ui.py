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
    return render_template('collections.html')
