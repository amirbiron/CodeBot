from __future__ import annotations

from flask import Blueprint, render_template

snippet_library_ui = Blueprint('snippet_library_ui', __name__)


@snippet_library_ui.route('/snippets')
def snippets_page():
    return render_template('snippets.html')
