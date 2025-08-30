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
# עדכון חבילות מערכת ושדרוג כלי פייתון בסיסיים (pip/setuptools/wheel)
RUN apk upgrade --no-cache && \
    python -m pip install --upgrade --no-cache-dir 'pip>=24.1' 'setuptools>=78.1.1' 'wheel>=0.43.0'
# התקנת תלויות מערכת לבילד (נדרש ל-build של psutil וכד')
RUN apk add --no-cache gcc g++ musl-dev python3-dev linux-headers

# יצירת משתמש לא-root
# Alpine: create non-root user
RUN addgroup -g 1000 botuser && \
    adduser -D -s /bin/sh -u 1000 -G botuser botuser

# יצירת תיקיות עבודה
WORKDIR /app

# העתקת requirements והתקנת dependencies (Production-only)
COPY requirements.prod.txt requirements.txt
COPY constraints.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

######################################
# שלב 2: Production stage (Alpine)
FROM python:3.11-alpine3.20 AS production

# משתני סביבה לייצור
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/home/botuser/.local/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"
# התקנת תלויות runtime
RUN apk upgrade --no-cache && apk add --no-cache \
    cairo pango gdk-pixbuf fontconfig ttf-dejavu tzdata curl \
    libxml2 sqlite-libs zlib

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
