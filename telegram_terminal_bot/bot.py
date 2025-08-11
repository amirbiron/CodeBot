import asyncio
import os
import shlex
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Configuration via environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = {uid.strip() for uid in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if uid.strip()}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Basic safe command whitelist and working directory

def _resolve_workdir() -> Path:
    env_dir = os.getenv("WORKDIR")
    candidates = []
    if env_dir:
        candidates.append(env_dir)
    candidates.extend(["/app", "/workspace"]) 
    for p in candidates:
        try:
            if p and Path(p).exists():
                return Path(p).resolve()
        except Exception:
            continue
    return Path.cwd().resolve()

WORKDIR = _resolve_workdir()
logging.info(f"Working directory: {WORKDIR}")
SAFE_PREFIXES = [
    # Filesystem
    "pwd",
    "ls",
    "ls ",
    "cd ",
    "find ",
    "cat ",
    "tail ",
    "head ",
    "du -sh",
    "df -h",

    # System
    "whoami",
    "id",
    "ps aux",
    "top -b -n 1",
    "uptime",
    "free -h",
    "uname -a",

    # Network
    "curl ",
    "wget ",
    "ping -c ",

    # Dev & tooling (Render env may not have all)
    "git ",
    "pip ",
    "pip3 ",
    "python ",
    "python3 ",

    # Text processing
    "grep ",
    "sed ",
    "awk ",

    # Docker (likely unavailable on Render)
    "docker version",
    "docker images",
    "docker ps",
    "docker run ",
    "docker build ",
    "sudo docker ",
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Bot is up. Send a shell command (limited whitelist). Example: 'docker version'")


def is_authorized(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    user = update.effective_user
    return user and str(user.id) in ALLOWED_USER_IDS


def is_safe_command(cmd: str) -> bool:
    cmd = cmd.strip()
    return any(cmd.startswith(prefix) for prefix in SAFE_PREFIXES)


async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized user.")
        return

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not is_safe_command(text):
        await update.message.reply_text("Command not allowed. Allowed prefixes: " + ", ".join(SAFE_PREFIXES))
        return

    # Execute command using bash -lc to support shell features safely
    try:
        cwd_path = WORKDIR if WORKDIR.exists() else Path.cwd()
        proc = await asyncio.create_subprocess_shell(
            text,
            cwd=str(cwd_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")
        header = f"$ {text}\n(exit {proc.returncode})\n"
        reply = (header + output).strip()
        # Telegram message limit ~4096 chars
        if len(reply) > 3900:
            reply = reply[:3800] + "\n... (truncated)"
        await update.message.reply_text(reply)
    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "פקודות מותרות (דוגמאות):\n"
        "- קבצים: pwd, ls -la, cd DIR && ls, find . -maxdepth 2 -type f\n"
        "- קריאה: cat README.md, head -n 50 file.txt, tail -n 100 file.txt\n"
        "- מערכת: whoami, id, ps aux, top -b -n 1, uptime, free -h, uname -a\n"
        "- רשת: curl https://example.com, ping -c 3 8.8.8.8\n"
        "- קוד: git status, pip --version, python --version\n"
        "- טקסט: grep 'pattern' file.txt, sed 's/a/b/g' file.txt, awk '{print $1}' file.txt\n"
        "הערה: ב-Render יתכן שכלי מסוימים לא מותקנים (למשל docker).\n"
    )


def main() -> None:
    token = BOT_TOKEN
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, run_command))

    allowed_info = "all users" if not ALLOWED_USER_IDS else ", ".join(sorted(ALLOWED_USER_IDS))
    logging.info(f"Starting bot. Allowed users: {allowed_info}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()