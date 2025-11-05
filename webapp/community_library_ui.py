from __future__ import annotations

from flask import Blueprint, render_template

community_library_ui = Blueprint('community_library_ui', __name__)


@community_library_ui.route('/community-library')
def community_library_page():
    return render_template('community_library.html')
