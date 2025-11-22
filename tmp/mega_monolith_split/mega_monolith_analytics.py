"""
מודול עבור: aggregate_user_stats, generate_report_json, calculate_engagement, calculate_vat
"""

import json

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



def calculate_vat(amount):
    return round(amount * 0.17, 2)


