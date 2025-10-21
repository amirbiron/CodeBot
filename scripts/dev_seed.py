#!/usr/bin/env python3
"""
Seed deterministic data for local development.
- Creates a demo user and several code_snippets with various languages
- Prints IDs to stdout so agents can plug into Postman env

Safety: Only runs against MongoDB pointed by env vars; refuses to run if not localhost unless --allow-nonlocal passed.
"""
import os
import sys
import logging
import socket
import ipaddress
from urllib.parse import urlparse
from datetime import datetime, timezone
from pymongo import MongoClient

def _split_hosts(hosts_str: str) -> list[str]:
    """Split a MongoDB hosts string by commas, respecting IPv6 bracket notation.
    Example: "localhost:27017,[::1]:27017,127.0.0.1" -> ["localhost:27017", "[::1]:27017", "127.0.0.1"]
    """
    parts: list[str] = []
    buf: str = ""
    in_brackets = False
    for ch in hosts_str:
        if ch == '[':
            in_brackets = True
        elif ch == ']':
            in_brackets = False
        if ch == ',' and not in_brackets:
            if buf:
                parts.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _host_from_token(token: str) -> str:
    token = token.strip()
    # IPv6 with brackets
    if token.startswith('['):
        end = token.find(']')
        host = token[1:end] if end != -1 else token.strip('[]')
        return host
    # hostname or IPv4 (optionally with :port)
    if ':' in token:
        return token.split(':', 1)[0]
    return token


def _is_loopback_host(host: str) -> bool:
    try:
        # Exact localhost shortcut
        if host == 'localhost':
            return True
        # Literal IP
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_loopback
        except ValueError:
            pass
        # Resolve and ensure all addresses are loopback
        infos = socket.getaddrinfo(host, None)
        ips = {info[4][0] for info in infos if info and info[4]}
        if not ips:
            return False
        return all(ipaddress.ip_address(ip).is_loopback for ip in ips)
    except Exception:
        return False


def is_local_mongo(url: str) -> bool:
    """Strictly allow only loopback MongoDB URIs.

    Rules:
    - mongodb:// may contain a comma-separated host list; ALL must resolve to loopback.
    - mongodb+srv:// allowed only if the hostname resolves exclusively to loopback.
    - Substring checks are NOT used.
    """
    if not url:
        return False
    p = urlparse(url)
    if p.scheme not in ("mongodb", "mongodb+srv"):
        return False
    # Remove credentials from netloc
    netloc = p.netloc.split('@', 1)[-1]
    if p.scheme == 'mongodb':
        hosts_tokens = _split_hosts(netloc)
        hosts = [_host_from_token(t) for t in hosts_tokens]
        return bool(hosts) and all(_is_loopback_host(h) for h in hosts)
    else:  # mongodb+srv
        # SRV records can point anywhere; require the visible hostname to be loopback-only
        host = p.hostname or ""
        return _is_loopback_host(host)


logger = logging.getLogger(__name__)


def main():
    allow_nonlocal = "--allow-nonlocal" in sys.argv
    mongo_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017/code_keeper")
    db_name = os.getenv("DATABASE_NAME", "code_keeper_bot")

    if not allow_nonlocal and not is_local_mongo(mongo_url):
        logger.error("Refusing to seed non-local MongoDB. Pass --allow-nonlocal to override.")
        sys.exit(1)

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000, tz_aware=True)
    client.server_info()
    db = client[db_name]

    # Demo user
    user_id = 123456
    db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "username": "demo_user",
            "first_name": "Demo",
            "last_name": "User",
            "ui_prefs": {"font_scale": 1.0, "theme": "classic"},
            "updated_at": datetime.now(timezone.utc)
        }, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True
    )

    samples = [
        ("hello.py", "python", "def hello():\n    return 'world'\n"),
        ("index.html", "html", "<html><body><h1>Hello</h1></body></html>\n"),
        ("README.md", "markdown", "# Demo\n\n- item 1\n- item 2\n"),
        ("app.js", "javascript", "export function sum(a,b){ return a+b }\n"),
    ]

    inserted_ids = []
    for name, lang, code in samples:
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user_id,
            "file_name": name,
            "programming_language": lang,
            "code": code,
            "description": f"Seeded example for {name}",
            "tags": ["seed", lang],
            "created_at": now,
            "updated_at": now,
            "is_active": True,
        }
        res = db.code_snippets.insert_one(doc)
        inserted_ids.append(str(res.inserted_id))

    logger.info("Seed completed.")
    logger.info("user_id=%s", user_id)
    for i, _id in enumerate(inserted_ids, 1):
        logger.info("file_id_%s=%s", i, _id)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Seed failed")
        sys.exit(1)
