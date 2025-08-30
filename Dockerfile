# ===================================
# Code Keeper Bot - Production Dockerfile (Chainguard Python)
# ===================================

# שלב 1: Build stage (wheel build if needed)
FROM python:3.11-alpine3.20 AS builder

# מידע על התמונה
LABEL maintainer="Code Keeper Bot Team"
LABEL version="1.0.0"
LABEL description="Advanced Telegram bot for managing code snippets"

# משתני סביבה לבילד
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=100
ENV PIP_INDEX_URL=https://pypi.org/simple
# עדכון חבילות מערכת ושדרוג כלי פייתון בסיסיים (pip/setuptools/wheel)
RUN apk upgrade --no-cache && \
    python -m pip install --upgrade --no-cache-dir 'pip>=24.1' 'setuptools>=78.1.1' 'wheel>=0.43.0'
# התקנת תלויות מערכת לבילד (נדרש ל-build של psutil וכד')
RUN apk add --no-cache \
    gcc=13.2.1_git20240309-r1 \
    g++=13.2.1_git20240309-r1 \
    musl-dev=1.2.5-r1 \
    python3-dev=3.12.11-r0 \
    linux-headers=6.6-r0

# יצירת משתמש לא-root
# Alpine: create non-root user
RUN addgroup -g 1000 botuser && \
    adduser -D -s /bin/sh -u 1000 -G botuser botuser

# יצירת תיקיות עבודה
WORKDIR /app

# העתקת requirements והתקנת dependencies (Production-only)
COPY requirements.prod.txt requirements.txt
COPY constraints.txt .
RUN pip install --user --no-cache-dir -r requirements.txt -c constraints.txt --retries 5 --timeout 60 -i https://pypi.org/simple

######################################
# שלב 2: Production stage (Alpine)
FROM python:3.11-alpine3.20 AS production

# משתני סביבה לייצור
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/home/botuser/.local/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"
ENV PYTHONFAULTHANDLER=1
# התקנת תלויות runtime
RUN apk upgrade --no-cache && apk add --no-cache \
    cairo=1.18.4-r0 \
    pango=1.52.2-r0 \
    gdk-pixbuf=2.42.12-r0 \
    fontconfig=2.15.0-r1 \
    font-dejavu=2.37-r5 \
    tzdata=2025b-r0 \
    curl=8.12.1-r0 \
    libxml2=2.12.10-r0 \
    sqlite-libs=3.45.3-r2 \
    zlib=1.3.1-r1

# שדרוג כלי פייתון בסיסיים גם בשכבת ה-production כדי למנוע CVEs ב-site-packages של המערכת
RUN python -m pip install --upgrade --no-cache-dir 'pip>=24.1' 'setuptools>=78.1.1' 'wheel>=0.43.0'

# יצירת משתמש לא-root
# Alpine: create non-root user
RUN addgroup -g 1000 botuser && \
    adduser -D -s /bin/sh -u 1000 -G botuser botuser

# יצירת תיקיות
RUN mkdir -p /app /app/logs /app/backups /app/temp \
    && chown -R botuser:botuser /app

# העתקת Python packages מ-builder stage
COPY --from=builder --chown=botuser:botuser /root/.local /home/botuser/.local

# מעבר למשתמש לא-root
USER botuser
WORKDIR /app

# העתקת קבצי האפליקציה
COPY --chown=botuser:botuser . .

# הגדרת timezone
ENV TZ=UTC

# פורטים (Render auto-assigns PORT)
EXPOSE ${PORT:-8000}

# בדיקת תקינות - מותאם לRender
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; \
try: \
    from config import config; \
    from database import db; \
    assert config.BOT_TOKEN, 'BOT_TOKEN missing'; \
    print('Health check passed'); \
    sys.exit(0); \
except Exception as e: \
    print(f'Health check failed: {e}'); \
    sys.exit(1);"

# פקודת הפעלה - Render compatible
CMD ["sh", "-c", "python main.py"]

######################################
# שלב dev נפרד הוסר; משתמשים באותו בסיס בטוח
