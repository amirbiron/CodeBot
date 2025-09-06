# ===================================
# Code Keeper Bot - Production Dockerfile (Chainguard Python)
# ===================================

# שלב 1: Build stage (wheel build if needed)
FROM python:3.12-slim AS builder

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
RUN apt-get update -y && apt-get upgrade -y && \
    python -m pip install --upgrade --no-cache-dir 'pip>=24.1' 'setuptools>=78.1.1' 'wheel>=0.43.0'
# Build deps for wheels
RUN apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libc6-dev \
    libffi-dev \
    libssl-dev \
    pkg-config && \
    rm -rf /var/lib/apt/lists/*

# בשכבת ה-build אין צורך במשתמש נפרד (נשתמש ב-root); המשתמש ייווצר רק בשכבת ה-production

# יצירת תיקיות עבודה
WORKDIR /app

# העתקת requirements והתקנת dependencies (Production-only)
COPY requirements.prod.txt requirements.txt
COPY constraints.txt .
RUN pip install --user --no-cache-dir -r requirements.txt -c constraints.txt --retries 5 --timeout 60 -i https://pypi.org/simple

######################################
# שלב 2: Production stage (Alpine)
FROM python:3.12-slim AS production

# משתני סביבה לייצור
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/home/botuser/.local/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"
ENV PYTHONFAULTHANDLER=1
# התקנת תלויות runtime
RUN apt-get update -y && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    fontconfig \
    fonts-dejavu \
    tzdata \
    curl \
    libxml2 \
    sqlite3 \
    zlib1g && \
    rm -rf /var/lib/apt/lists/*

# שדרוג כלי פייתון בסיסיים גם בשכבת ה-production כדי למנוע CVEs ב-site-packages של המערכת
RUN python -m pip install --upgrade --no-cache-dir 'pip>=24.1' 'setuptools>=78.1.1' 'wheel>=0.43.0'

# יצירת משתמש לא-root
# Alpine: create non-root user
RUN groupadd -g 1000 botuser && \
    useradd -m -s /bin/bash -u 1000 -g 1000 botuser

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

# פקודת הפעלה - Render compatible (אפשרות ל-WebApp במקביל)
ENV WEBAPP_ENABLED=0
ENV WEBAPP_PORT=8000
CMD ["sh", "-c", "if [ \"$WEBAPP_ENABLED\" = \"1\" ]; then (uvicorn webapp.server:app --host 0.0.0.0 --port ${PORT:-$WEBAPP_PORT} &) ; fi; python main.py"]

######################################
# שלב dev נפרד הוסר; משתמשים באותו בסיס בטוח
