"""
מודול עבור: debug_dump_state, mega_function_messy
"""

import json

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


