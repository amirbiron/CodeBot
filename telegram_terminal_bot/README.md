# Telegram Terminal Bot (safe, whitelisted)

Requirements:
- Python 3.11+
- Packages from `requirements.txt`
- Environment: `TELEGRAM_BOT_TOKEN` (and optional `TELEGRAM_ALLOWED_USER_IDS` as comma-separated numeric IDs)

Setup:
```bash
cd /workspace/telegram_terminal_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
# optionally restrict who can use the bot
export TELEGRAM_ALLOWED_USER_IDS=123456789
python bot.py
```

Usage:
- In Telegram, send the bot shell commands that start with one of the allowed prefixes.
- Examples:
  - `docker version`
  - `docker run --rm hello-world`
  - `ls -la`

Notes:
- The bot runs commands in `/workspace`.
- Docker commands are allowed; for privileged actions it supports `sudo docker ...`.
- Output is truncated around 4000 characters to fit Telegram limits.