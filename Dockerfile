# syntax=docker/dockerfile:1.6
# ===================================
# Code Keeper Bot - Production Dockerfile (Playwright base)
# ===================================

######################################
# שלב 1: Build stage (pip wheels + cache)
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy AS builder

LABEL maintainer="Code Keeper Bot Team"
LABEL version="1.1.0"
LABEL description="Advanced Telegram bot for managing code snippets"

USER root

# משתני סביבה לבילד
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_INDEX_URL=https://pypi.org/simple \
    DEBIAN_FRONTEND=noninteractive

# כלים לבניית חבילות heavy (wheels)
RUN apt-get update -y && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev \
        libc6-dev \
        libffi-dev \
        libssl-dev \
        pkg-config \
        libjpeg-dev \
        zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade --no-cache-dir 'pip>=24.1' 'setuptools>=78.1.1' 'wheel>=0.43.0'

WORKDIR /app

# העתקת requirements והתקנת dependencies (Production-only)
COPY requirements/ /app/requirements/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user -r /app/requirements/production.txt --retries 5 --timeout 60

# יצירת constraints לשחזור צפוי
RUN python -m pip freeze | sort > /app/constraints.txt

# אימות התקנה מול constraints
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user -r /app/requirements/production.txt -c /app/constraints.txt --retries 5 --timeout 60

######################################
# שלב 2: Production stage (Playwright base)
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy AS production

USER root

# משתני סביבה לייצור
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/home/botuser/.local/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DEBIAN_FRONTEND=noninteractive

# חבילות Runtime הנדרשות מעבר למה שקיים בבייס (בעיקר פונטים/כלים)
RUN apt-get update -y && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-dejavu \
        fonts-jetbrains-mono \
        fonts-cascadia-code \
        tzdata \
        curl \
        libxml2 \
        sqlite3 \
        nodejs \
        npm && \
    fc-cache -f -v && \
    rm -rf /var/lib/apt/lists/*

# שמירה על גרסאות pip/setuptools מעודכנות
RUN python -m pip install --upgrade --no-cache-dir 'pip>=24.1' 'setuptools>=78.1.1' 'wheel>=0.43.0'

# יצירת משתמש לא-root (אידמפוטנטי גם אם ה-UID/GID כבר תפוסים בבייס)
ARG BOT_UID=1000
ARG BOT_GID=1000
RUN set -eux; \
    if getent group "${BOT_GID}" >/dev/null 2>&1; then \
        GROUP_FLAGS="-g ${BOT_GID} -o"; \
    else \
        GROUP_FLAGS="-g ${BOT_GID}"; \
    fi; \
    if ! getent group botuser >/dev/null 2>&1; then \
        groupadd ${GROUP_FLAGS} botuser; \
    fi; \
    if getent passwd "${BOT_UID}" >/dev/null 2>&1; then \
        USER_FLAGS="-u ${BOT_UID} -o"; \
    else \
        USER_FLAGS="-u ${BOT_UID}"; \
    fi; \
    if ! id -u botuser >/dev/null 2>&1; then \
        useradd ${USER_FLAGS} -m -s /bin/bash -g botuser botuser; \
    fi; \
    mkdir -p /app /app/logs /app/backups /app/temp; \
    chown -R botuser:botuser /app

# העתקת Python packages ו-constraints מה-builder stage
COPY --from=builder --chown=botuser:botuser /root/.local /home/botuser/.local
COPY --from=builder --chown=botuser:botuser /app/constraints.txt /app/constraints.txt

USER botuser
WORKDIR /app

# העתקת קבצי האפליקציה
COPY --chown=botuser:botuser . .

# התקנת תלויות ה-Worker (Node)
RUN npm --prefix push_worker install --omit=dev && npm cache clean --force

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

# פקודת הפעלה - מריץ Worker (אם דגל מופעל) ואת ה-WebApp
RUN chmod +x scripts/start_with_worker.sh
CMD ["sh", "-c", "scripts/start_with_worker.sh"]

######################################
# שלב dev נפרד הוסר; משתמשים באותו בסיס בטוח
