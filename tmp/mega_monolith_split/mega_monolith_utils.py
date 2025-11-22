"""
מודול עבור: slugify, deep_merge, random_id
"""

import random

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


