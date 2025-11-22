"""
מודול עבור: full_purchase_flow, upload_file_flow
"""


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


