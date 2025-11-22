"""
מודול עבור: application_boot, load_users_fake_db, demo_inventory
"""

from .mega_monolith_classes import EmailService, ExternalStatsClient, FileStore, FileValidator, Inventory, NotificationManager, PaymentGateway, Product, SubscriptionManager, User

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



def load_users_fake_db():
    return [
        User(1, "Amir", "amir@example.com", True, "premium"),
        User(2, "Lior", "lior@example.com", False, "free"),
        User(3, "Dana", "dana@example.com", False, "pro"),
    ]



def demo_inventory():
    inv = Inventory()
    inv.add(Product(1, "Laptop", 3500, "tech"))
    inv.add(Product(2, "Mouse", 80, "tech"))
    inv.add(Product(3, "Notebook", 15, "stationary"))
    return inv


