"""Webapp routes package.

This package contains modularized route blueprints as part of the layered
architecture refactoring (Issue #2871 - Step 3: The Great Split).

Available Blueprints (import directly from submodules):
- files_bp: webapp.routes.files_routes
- auth_bp: webapp.routes.auth_routes
- settings_bp: webapp.routes.settings_routes
- dashboard_bp: webapp.routes.dashboard_routes

Note: Imports are NOT done at package level to avoid cascade failures.
Each blueprint should be imported directly from its module in app.py.
"""
