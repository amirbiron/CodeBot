"""
מחלקות שהופקו מהמונולית
"""

import os
import json

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

class PaymentGateway:
    def init(self, key):
        self.key = key

    def charge(self, user: User, amount: float):
        if user.tier == "free":
            raise ValueError("Free tier users cannot be charged.")
        if amount <= 0:
            raise ValueError("Invalid amount")
        return {"status": "ok", "amount": amount, "user_id": user.user_id}

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

class ApiClient:
    BASE = "https://api.example.com"

    def get(self, endpoint):
        return {"method": "GET", "url": self.BASE + endpoint}

    def post(self, endpoint, data):
        return {"method": "POST", "url": self.BASE + endpoint, "data": data}

class ExternalStatsClient:
    def fetch_stats(self, user_id):
        return {"user_id": user_id, "visits": 42, "likes": 12}

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

