# ===================================
# Code Keeper Bot - Production Dockerfile (Chainguard Python)
# ===================================

# שלב 1: Build stage (wheel build if needed)
FROM cgr.dev/chainguard/python:latest AS builder

# מידע על התמונה
LABEL maintainer="Code Keeper Bot Team"
LABEL version="1.0.0"
LABEL description="Advanced Telegram bot for managing code snippets"

# משתני סביבה לבילד
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
# הימנע מדיאלוגים אינטראקטיביים בזמן build
ENV DEBIAN_FRONTEND=noninteractive

# התקנת תלויות מערכת לבילד
# hadolint ignore=DL3008
RUN set -eux; \
    apt-get update || (sed -i 's|http://|https://|g' /etc/apt/sources.list && apt-get update); \
    # שדרוג תיקוני אבטחה של מערכת בסיס
    apt-get -y upgrade; \
    apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    ; \
    rm -rf /var/lib/apt/lists/*

# יצירת משתמש לא-root
RUN groupadd -r botuser && useradd -r -g botuser botuser

# יצירת תיקיות עבודה
WORKDIR /app

# העתקת requirements והתקנת dependencies
COPY requirements.txt .
COPY constraints.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

######################################
# שלב 2: Production stage (Chainguard)
FROM cgr.dev/chainguard/python:latest AS production

# משתני סביבה לייצור
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/home/botuser/.local/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"
# הימנע מדיאלוגים אינטראקטיביים בזמן build
ENV DEBIAN_FRONTEND=noninteractive

# התקנת תלויות runtime
# hadolint ignore=DL3008,DL4006
RUN set -eux; \
    apt-get update || (sed -i 's|http://|https://|g' /etc/apt/sources.list && apt-get update); \
    # שדרוג תיקוני אבטחה כדי לטפל ב‑zlib/libxml2/sqlite וכד'
    apt-get -y upgrade; \
    echo "tzdata tzdata/Areas select Etc" | debconf-set-selections; \
    echo "tzdata tzdata/Zones/Etc select UTC" | debconf-set-selections; \
    apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    fontconfig \
    fonts-dejavu-core \
    curl \
    ca-certificates \
    tzdata \
    ; \
    update-ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    apt-get clean

# יצירת משתמש לא-root
RUN groupadd -r botuser && useradd -r -g botuser botuser

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
