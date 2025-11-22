# -*- coding: utf-8 -*-
"""
MEGA MONOLITH TEST FILE
קובץ ענק לפיצול למודולים.
הכול מעורבב יחד: משתמשים, תשלומים, פריטים, קבצים, לוג אינטרנט, סטטיסטיקות,
מערכת הרשאות, לוגיקת נוטיפיקציות, תמונות, דוחו"ת, דאטה-בייס מדומה,
ועוד הרבה בלגן. זהו קובץ שמטרתו לבדוק האם מנוע ה-refactor שלך יודע:

✔ לזהות שכבות
✔ לפצל לקבצים
✔ לאחד קוד חוזר
✔ לזהות תחומים שונים
✔ ליצור מבנה מודולים הגיוני
✔ לארגן imports אוטומטית
"""

#############################
# 1) USER MANAGEMENT
#############################

class User:
    def init(self, user_id, name, email, is_admin=False, tier="free"):
        self.user_id = user_id
        self.name = name
        self.email = email
        self.is_admin = is_admin
        self.tier = tier
        self.permissions = []

    def can(self, perm):
        return perm in self.permissions or self.is_admin

    def assign(self, perm):
        if perm not in self.permissions:
            self.permissions.append(perm)


class UserManager:
    def init(self):
        self.users = {}

    def add(self, user: User):
        self.users[user.user_id] = user

    def get(self, user_id):
        return self.users.get(user_id)

    def validate_email(self, email):
        return "@" in email and "." in email


def load_users_fake_db():
    return [
        User(1, "Amir", "amir@example.com", True, "premium"),
        User(2, "Lior", "lior@example.com", False, "free"),
        User(3, "Dana", "dana@example.com", False, "pro"),
    ]


#############################
# 2) PAYMENTS + SUBSCRIPTIONS
#############################

class PaymentGateway:
    def init(self, key):
        self.key = key

    def charge(self, user: User, amount: float):
        if user.tier == "free":
            raise ValueError("Free tier users cannot be charged.")
        if amount <= 0:
            raise ValueError("Invalid amount")
        return {"status": "ok", "amount": amount, "user_id": user.user_id}


def calculate_vat(amount):
    return round(amount * 0.17, 2)


class SubscriptionManager:
    def init(self):
        self.subscriptions = {}

    def subscribe(self, user, plan):
        self.subscriptions[user.user_id] = plan

    def get_plan(self, user):
        return self.subscriptions.get(user.user_id, "free")

    def invoice(self, user, items):
        subtotal = sum([i["price"] for i in items])
        vat = calculate_vat(subtotal)
        total = subtotal + vat
        return {
            "user": user.name,
            "plan": self.get_plan(user),
            "subtotal": subtotal,
            "vat": vat,
            "total": total,
            "items": items,
        }


#############################
# 3) FILE SYSTEM
#############################

import os
import json

class FileStore:
    def save(self, path, content):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def read(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


class FileValidator:
    def validate_name(self, name):
        return "." in name and len(name) > 3

    def validate_json(self, content):
        try:
            json.loads(content)
            return True
        except:
            return False


#############################
# 4) INVENTORY / PRODUCTS
#############################

class Product:
    def init(self, pid, title, price, category):
        self.pid = pid
        self.title = title
        self.price = price
        self.category = category


class Inventory:
    def init(self):
        self.items = {}

    def add(self, product: Product):
        self.items[product.pid] = product

    def find_by_category(self, category):
        return [p for p in self.items.values() if p.category == category]

    def total_value(self):
        return sum(p.price for p in self.items.values())

def demo_inventory():
    inv = Inventory()
    inv.add(Product(1, "Laptop", 3500, "tech"))
    inv.add(Product(2, "Mouse", 80, "tech"))
    inv.add(Product(3, "Notebook", 15, "stationary"))
    return inv


#############################
# 5) NETWORK / API CLIENTS
#############################

class ApiClient:
    BASE = "https://api.example.com"

    def get(self, endpoint):
        return {"method": "GET", "url": self.BASE + endpoint}

    def post(self, endpoint, data):
        return {"method": "POST", "url": self.BASE + endpoint, "data": data}


class ExternalStatsClient:
    def fetch_stats(self, user_id):
        return {"user_id": user_id, "visits": 42, "likes": 12}


#############################
# 6) ANALYTICS / REPORTS
#############################

def aggregate_user_stats(users, stats_client):
    out = []
    for u in users:
        stats = stats_client.fetch_stats(u.user_id)
        out.append({
            "user": u.name,
            "visits": stats["visits"],
            "likes": stats["likes"],
            "tier": u.tier,
        })
    return out


def generate_report_json(stats):
    return json.dumps({"stats": stats}, indent=2, ensure_ascii=False)


def calculate_engagement(visits, likes):
    if visits == 0:
        return 0
    return round((likes / visits) * 100, 2)


#############################
# 7) NOTIFICATIONS
#############################

class EmailService:
    def send(self, to, subject, body):
        return {"ok": True, "to": to, "subject": subject, "body": body}


class NotificationManager:
    def init(self, email_service):
        self.email_service = email_service

    def notify_purchase(self, user, invoice):
        return self.email_service.send(
            user.email,
            "רכישה בוצעה בהצלחה",
            f"היי {user.name}, הסכום: {invoice['total']}₪"
        )

    def notify_file_upload(self, user, filename):
        return self.email_service.send(
            user.email,
            "קובץ נשמר",
            f"היי {user.name}, הקובץ '{filename}' נשמר בהצלחה."
        )


#############################
# 8) PERMISSIONS / AUTH LOGIC
#############################

class PermissionSystem:
    def init(self):
        self.mapping = {
            "upload": "can_upload_files",
            "purchase": "can_purchase",
            "admin": "is_admin"
        }

    def has_permission(self, user, action):
        key = self.mapping.get(action)
        if key == "is_admin":
            return user.is_admin
        return key in user.permissions


#############################
# 9) WORKFLOW / PIPELINES
#############################

def full_purchase_flow(user, items, gateway, sub_manager, notif):
    invoice = sub_manager.invoice(user, items)
    gateway.charge(user, invoice["total"])
    notif.notify_purchase(user, invoice)
    return invoice


def upload_file_flow(user, filename, content, validator, store, notif):
    if not validator.validate_name(filename):
        raise ValueError("Bad filename")
    store.save(filename, content)
    notif.notify_file_upload(user, filename)
    return True


#############################
# 10) DEBUG / TEMP / MIXED
#############################

def debug_dump_state(users, inv, subs):
    dump = {
        "users": [u.to_dict() for u in users],
        "inventory_total": inv.total_value(),
        "subscriptions": subs.subscriptions,
    }
    return json.dumps(dump, indent=2, ensure_ascii=False)


def mega_function_messy(a, b, c, flag):
    # בלאגן של ifים
    if a > 10:
        if b < 5:
            if flag:
                return a + b + c
        else:
            if c > 100:
                return "BIG"
            else:
                if a == b:
                    return "EQ"
    elif a < 0:
        if c < -1000:
            return "NEG-EXTREME"
    return "UNKNOWN"


#############################
# 11) RANDOM UTILITIES
#############################

def slugify(text):
    return text.lower().replace(" ", "-")

def deep_merge(a, b):
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and k in out and isinstance(out[k], dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def random_id(prefix="ID"):
    import random
    return prefix + str(random.randint(100000, 999999))


#############################
# 12) APPLICATION BOOT (מדמה main)
#############################

def application_boot():
    users = load_users_fake_db()
    inv = demo_inventory()
    subs = SubscriptionManager()
    stats_client = ExternalStatsClient()
    gateway = PaymentGateway("key-xyz")
    email = EmailService()
    notif = NotificationManager(email)

    # תהליכים מלאים
    stats = aggregate_user_stats(users, stats_client)
    print(generate_report_json(stats))

    invoice = full_purchase_flow(
        users[0],
        [{"price": 49}, {"price": 10}],
        gateway,
        subs,
        notif,
    )
    print(invoice)

    upload_file_flow(users[1], "notes.json", '{"ok": true}', FileValidator(), FileStore(), notif)

    print(debug_dump_state(users, inv, subs))
