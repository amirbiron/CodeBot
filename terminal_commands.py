"""
Terminal commands: sandboxed command execution via Docker containers.
"""
import asyncio
import logging
import shlex
import shutil
from html import escape as html_escape
from typing import Tuple

from telegram import Update, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, MessageHandler, ConversationHandler,
                          ContextTypes, filters)

logger = logging.getLogger(__name__)

# Conversation states
TERMINAL_ACTIVE = 1

# UI
TERMINAL_KEYBOARD = ReplyKeyboardMarkup([["🚪 יציאה מטרמינל"]], resize_keyboard=True)

DOCKER_IMAGE = "alpine:3.20"

async def _check_docker_available() -> bool:
    """Return True if docker CLI is available and usable."""
    if not shutil.which("docker"):
        return False
    # quick version check with small timeout
    try:
        proc = await asyncio.create_subprocess_shell(
            "docker version --format '{{.Server.Version}}'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=3)
            return proc.returncode == 0
        except asyncio.TimeoutError:
            proc.kill()
            return False
    except Exception:
        return False

async def run_in_sandbox(command: str, timeout_sec: int = 10, max_output_chars: int = 3500) -> Tuple[int, str]:
    """Run a shell command inside a locked-down Docker container and return (rc, output)."""
    # Use a restricted container with no network, non-root, read-only FS, tmpfs for /tmp and /sandbox
    docker_cmd = (
        "docker run --rm --network none --cpus=0.5 --memory=256m --pids-limit=128 "
        "--read-only --tmpfs /tmp:rw,size=64m --tmpfs /sandbox:rw,size=64m "
        "--workdir /sandbox --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges "
        f"{DOCKER_IMAGE} sh -lc {shlex.quote(command)}"
    )

    proc = await asyncio.create_subprocess_shell(
        docker_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        output = (stdout.decode() + stderr.decode())
        truncated = False
        if len(output) > max_output_chars:
            output = output[:max_output_chars]
            truncated = True
        if truncated:
            output += "\n\n[פלט קוצר]"
        return proc.returncode, output
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return 124, "⏱️ פקודה חרגה ממגבלת הזמן"

async def terminal_enter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Enter terminal mode if Docker is available."""
    if not await _check_docker_available():
        await update.message.reply_text(
            "❌ מצב טרמינל לא זמין: Docker לא זמין בשרת",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "💻 נכנסת למצב טרמינל מוגבל\n\n"
        "מגבלות אבטחה ומשאבים:\n"
        "• ללא רשת (--network none)\n"
        "• זמן ריצה מקסימלי: 10 שניות\n"
        "• זיכרון: 256MB, CPU: 0.5 vCPU\n"
        "• מערכת קבצים לקריאה בלבד, עם /tmp ו-/sandbox זמניים\n"
        "• פלט מקסימלי: 3500 תווים (נחתך אוטומטית)\n\n"
        "הקלד פקודה להרצה, או לחץ '🚪 יציאה מטרמינל' כדי לצאת.",
        reply_markup=TERMINAL_KEYBOARD,
        parse_mode=ParseMode.HTML
    )
    return TERMINAL_ACTIVE

async def terminal_exit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Exit terminal mode."""
    await update.message.reply_text(
        "🔒 יצאת ממצב טרמינל.",
        reply_markup=ReplyKeyboardMarkup(context.application.bot_data.get('MAIN_KEYBOARD', [["🏠 תפריט ראשי"]]), resize_keyboard=True)
    )
    return ConversationHandler.END

async def terminal_run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Run a command string inside the sandbox and send the output."""
    cmd = (update.message.text or "").strip()
    if not cmd:
        return TERMINAL_ACTIVE

    # guard: prevent long inputs
    if len(cmd) > 500:
        await update.message.reply_text("❌ פקודה ארוכה מדי")
        return TERMINAL_ACTIVE

    await update.message.reply_text("🔄 מריץ...", reply_to_message_id=update.message.message_id)

    try:
        rc, output = await run_in_sandbox(cmd)
        header = f"✅ קוד יציאה: {rc}" if rc == 0 else f"⚠️ קוד יציאה: {rc}"
        # escape and wrap output
        safe_output = html_escape(output) if output else "(ללא פלט)"
        await update.message.reply_text(
            f"{header}\n\n<pre>{safe_output}</pre>",
            parse_mode=ParseMode.HTML,
            reply_markup=TERMINAL_KEYBOARD
        )
    except Exception as e:
        logger.error(f"Terminal command failed: {e}")
        await update.message.reply_text("❌ שגיאה בהרצת הפקודה", reply_markup=TERMINAL_KEYBOARD)

    return TERMINAL_ACTIVE

async def terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/terminal command to enter terminal mode."""
    return await terminal_enter(update, context)


def setup_terminal_handlers(application: Application):
    """Register terminal conversation handlers and commands."""
    # store main keyboard for exit handler
    application.bot_data['MAIN_KEYBOARD'] = [["➕ הוסף קוד חדש"], ["📚 הצג את כל הקבצים שלי", "📂 קבצים גדולים"], ["⚡ עיבוד Batch", "🔧 GitHub"], ["💻 טרמינל"]]

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("terminal", terminal_command),
            MessageHandler(filters.Regex("^💻 טרמינל$"), terminal_enter),
        ],
        states={
            TERMINAL_ACTIVE: [
                MessageHandler(filters.Regex("^🚪 יציאה מטרמינל$"), terminal_exit),
                MessageHandler(filters.TEXT & ~filters.COMMAND, terminal_run_command),
            ]
        },
        fallbacks=[MessageHandler(filters.Regex("^🚪 יציאה מטרמינל$"), terminal_exit)],
        allow_reentry=True,
        per_message=False,
    )
    application.add_handler(conv)
    logger.info("Terminal handlers הוגדרו בהצלחה")