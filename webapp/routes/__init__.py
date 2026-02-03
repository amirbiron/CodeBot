"""Webapp routes package.

This package contains modularized route blueprints as part of the layered
architecture refactoring (Issue #2871 - Step 3: The Great Split).

Available Blueprints:
- files_bp: /api/files endpoints
- auth_bp: /login, /logout, /auth/* endpoints
- settings_bp: /settings/* endpoints
- dashboard_bp: /dashboard and /api/dashboard/* endpoints
"""

from webapp.routes.auth_routes import auth_bp
from webapp.routes.dashboard_routes import dashboard_bp
from webapp.routes.files_routes import files_bp
from webapp.routes.settings_routes import settings_bp

__all__ = [
    "auth_bp",
    "dashboard_bp",
    "files_bp",
    "settings_bp",
]
