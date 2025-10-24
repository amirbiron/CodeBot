import importlib

# 1️⃣ בדיקת ייבוא config והדגל FEATURE_MY_COLLECTIONS
try:
    from config import config as cfg
    print("config_import=success", "FEATURE_MY_COLLECTIONS=", getattr(cfg, "FEATURE_MY_COLLECTIONS", None))
except Exception as e:
    print("config_import=error", type(e).__name__, e)

# 2️⃣ בדיקה אם ה-Blueprint רשום
app_mod = importlib.import_module("webapp.app")
app = app_mod.app
print("app._cfg_is_None=", getattr(app_mod, "_cfg", None) is None)
print("routes=", [str(r) for r in app.url_map.iter_rules() if str(r).startswith("/api/collections")])

# 3️⃣ בדיקת תגובה עם וללא session
with app.test_client() as c:
    print("unauth_status=", c.post("/api/collections", json={"name": "X"}).status_code)
    with c.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_data"] = {"first_name": "Test"}
    print("auth_status=", c.post("/api/collections", json={"name": "X"}).status_code)
