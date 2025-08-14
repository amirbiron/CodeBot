# ===================================
# Code Keeper Bot - Production Dockerfile
# בוט שומר קבצי קוד - דוקר לייצור
# ===================================

# שלב 1: Build stage
FROM python:3.11-slim as builder

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
RUN set -eux; \
    apt-get update; \
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
RUN pip install --user --no-cache-dir -r requirements.txt

# ===================================
# שלב 2: Production stage
FROM python:3.11-slim as production

# משתני סביבה לייצור
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/home/botuser/.local/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"
# הימנע מדיאלוגים אינטראקטיביים בזמן build
ENV DEBIAN_FRONTEND=noninteractive

# התקנת תלויות runtime
RUN set -eux; \
    apt-get update || (sed -i 's|http://|https://|g' /etc/apt/sources.list && apt-get update); \
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

# ===================================
# Multi-stage build עם development
# ===================================

FROM production as development

USER root

# התקנת כלי פיתוח
RUN set -eux; \
    apt-get update || (sed -i 's|http://|https://|g' /etc/apt/sources.list && apt-get update); \
    apt-get install -y --no-install-recommends \
    git \
    vim \
    htop \
    ca-certificates \
    ; \
    update-ca-certificates; \
    rm -rf /var/lib/apt/lists/*

# התקנת dev dependencies
COPY requirements-dev.txt* ./
RUN if [ -f requirements-dev.txt ]; then \
        pip install --user --no-cache-dir -r requirements-dev.txt; \
    fi

USER botuser

# Override עבור פיתוח
ENV DEBUG=true
ENV LOG_LEVEL=DEBUG

CMD ["python", "main.py"]

# ===================================
# Production slim build
# ===================================

FROM python:3.11-alpine as production-slim

# משתני סביבה
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# התקנת תלויות Alpine
RUN apk add --no-cache \
    gcc \
    python3-dev \
    musl-dev \
    cairo \
    pango \
    gdk-pixbuf \
    fontconfig \
    ttf-dejavu \
    tzdata \
    curl \
    linux-headers

# יצירת משתמש
RUN addgroup -g 1000 botuser && \
    adduser -D -s /bin/sh -u 1000 -G botuser botuser

# התקנת Python packages
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# העתקת קבצים
COPY --chown=botuser:botuser . .

# מעבר למשתמש
USER botuser

# בדיקת תקינות
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from config import config; print('OK')"

CMD ["python", "main.py"]
