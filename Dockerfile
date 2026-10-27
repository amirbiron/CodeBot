# syntax=docker/dockerfile:1.6
# ===================================
# Code Keeper Bot - Production Dockerfile (Debian slim)
# ===================================

# גרסאות מינימום למאגרי התעודות שהבנייה והתמונה סומכות עליהם (אירוע eMudhra/emSign,
# אוקטובר 2026). ARG שמוצהר לפני ה-FROM הראשון אינו זמין בתוך שלב עד שמצהירים עליו
# שם שוב, בלי ערך — ולכן כל שלב שמשתמש בהם מצהיר עליהם מחדש.
#
# PIP_MIN_VERSION: ב-pip 26.2.2 ההורדות נבדקות גם מול מאגר התעודות של מערכת ההפעלה
# וגם מול certifi שה-pip מביא בתוכו (pip/_internal/cli/index_command.py), ו-26.2.2 מביא
# certifi 2026.10.19. לכן כל שלב משדרג את pip לפני ה-pip install הראשון שלו.
# את השדרוג עצמו מוריד ה-pip של תמונת הבסיס (24.0 כשנבדק, 27.10.2026). לפני 24.2 הוא
# בודק רק מול ה-certifi שבתוכו (ב-24.0 זה 2023.07.22, שעוד כולל את G3), ולכן פקודת
# השדרוג מקבלת PIP_CERT עם מאגר התעודות של מערכת ההפעלה, שהשכבה שלפניה עדכנה ובדקה.
ARG PIP_MIN_VERSION=26.2.2
# CA_CERTIFICATES_MIN_VERSION: חבילת ca-certificates של Debian, מאגר התעודות של מערכת
# ההפעלה. 20250419+deb13u1 (trixie-security) מסירה את "emSign ECC Root CA - G3" ואת
# "Comodo AAA Services root". כל שלב עוצר את הבנייה אם מותקנת גרסה ישנה ממנה, כי
# apt-get upgrade לבדו לא מבטיח את זה כששכבת ה-apt נלקחת מ-cache.
ARG CA_CERTIFICATES_MIN_VERSION=20250419+deb13u1

######################################
# שלב 1: Build stage (pip wheels + cache)
FROM python:3.11-slim AS builder

LABEL maintainer="Code Keeper Bot Team"
LABEL version="1.1.0"
LABEL description="Advanced Telegram bot for managing code snippets"

USER root

ARG PIP_MIN_VERSION
ARG CA_CERTIFICATES_MIN_VERSION

# משתני סביבה לבילד
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_INDEX_URL=https://pypi.org/simple \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/root/.local/bin:$PATH"

# כלים לבניית חבילות heavy (wheels), ו-ca-certificates — ה-pip של השלב הזה מוריד את כל
# התלויות ובודק אותן גם מול מאגר התעודות של מערכת ההפעלה (ראו PIP_MIN_VERSION למעלה).
# כל פקודה בהצהרה משלה ולא בשרשרת &&: תחת set -e, כישלון בתוך שרשרת && שאחריה באות עוד
# פקודות אינו עוצר את ה-RUN, ואז apt-get install שנכשל היה עובר בשקט אל בדיקת הגרסה.
RUN set -eux; \
    . /etc/os-release; \
    printf 'deb http://deb.debian.org/debian %s main contrib non-free non-free-firmware\n' "$VERSION_CODENAME" > /etc/apt/sources.list.d/non-free.list; \
    printf 'deb http://deb.debian.org/debian %s-updates main contrib non-free non-free-firmware\n' "$VERSION_CODENAME" >> /etc/apt/sources.list.d/non-free.list; \
    printf 'deb http://security.debian.org/debian-security %s-security main contrib non-free non-free-firmware\n' "$VERSION_CODENAME" >> /etc/apt/sources.list.d/non-free.list; \
    apt-get update -y; \
    apt-get upgrade -y; \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev \
        libc6-dev \
        libffi-dev \
        libssl-dev \
        pkg-config \
        libjpeg-dev \
        zlib1g-dev \
        ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    : "${CA_CERTIFICATES_MIN_VERSION:?CA_CERTIFICATES_MIN_VERSION build arg must be set}"; \
    ca_version="$(dpkg-query -W -f='${Version}' ca-certificates)"; \
    if ! dpkg --compare-versions "$ca_version" ge "$CA_CERTIFICATES_MIN_VERSION"; then \
        echo "ca-certificates ${ca_version} is older than ${CA_CERTIFICATES_MIN_VERSION}" >&2; \
        exit 1; \
    fi

RUN PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    python -m pip install --upgrade --no-cache-dir "pip>=${PIP_MIN_VERSION}" 'setuptools>=78.1.1' 'wheel>=0.43.0'

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
# שלב 2: Production stage (Debian slim)
FROM python:3.11-slim AS production

# Node משמש כאן את push_worker (npm install בבנייה, ובזמן ריצה מי שמפעיל אותו הוא
# scripts/start_with_worker.sh) ואת ה-driver של Playwright (ראו PLAYWRIGHT_NODEJS_PATH למטה).
# ‏22.23.4 היא גרסת אבטחה (nodejs.org/dist/index.json), ומאגר
# השורשים המובנה בה כבר בלי "emSign ECC Root CA - G3" — נמדד ב-tls.rootCertificates, מול
# 18.20.5 שעוד סמך עליו. לקו 18 שהיה כאן אין גרסה מתוקנת: סוף החיים שלו היה ב-30.4.2025.
ARG NODE_MAJOR=22
ARG NODE_VERSION=22.23.4
ARG PIP_MIN_VERSION
ARG CA_CERTIFICATES_MIN_VERSION

USER root

# משתני סביבה לייצור
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/home/botuser/.local/bin:/root/.local/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH" \
    DEBIAN_FRONTEND=noninteractive
ENV NODE_MAJOR=${NODE_MAJOR} \
    NODE_VERSION=${NODE_VERSION}

# חבילות Runtime הנדרשות (כולל Playwright deps מלאים). כל פקודה בהצהרה משלה, מאותה
# סיבה כמו בשלב ה-builder: שרשרת && לפני בדיקת הגרסה הייתה בולעת כישלון של ההתקנה.
RUN set -eux; \
    . /etc/os-release; \
    printf 'deb http://deb.debian.org/debian %s main contrib non-free non-free-firmware\n' "$VERSION_CODENAME" > /etc/apt/sources.list.d/non-free.list; \
    printf 'deb http://deb.debian.org/debian %s-updates main contrib non-free non-free-firmware\n' "$VERSION_CODENAME" >> /etc/apt/sources.list.d/non-free.list; \
    printf 'deb http://security.debian.org/debian-security %s-security main contrib non-free non-free-firmware\n' "$VERSION_CODENAME" >> /etc/apt/sources.list.d/non-free.list; \
    apt-get update -y; \
    apt-get upgrade -y; \
    apt-get install -y --no-install-recommends \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libatspi2.0-0 \
        libcairo2 \
        libdbus-1-3 \
        libdrm2 \
        libgbm1 \
        libgdk-pixbuf-2.0-0 \
        libnspr4 \
        libnss3 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
        fontconfig \
        fonts-dejavu \
        fonts-jetbrains-mono \
        fonts-cascadia-code \
        fonts-ubuntu \
        fonts-unifont \
        tzdata \
        curl \
        ca-certificates \
        gnupg \
        xz-utils \
        libxml2 \
        sqlite3 \
        zlib1g \
        libjpeg62-turbo; \
    fc-cache -f -v; \
    rm -rf /var/lib/apt/lists/*; \
    : "${CA_CERTIFICATES_MIN_VERSION:?CA_CERTIFICATES_MIN_VERSION build arg must be set}"; \
    ca_version="$(dpkg-query -W -f='${Version}' ca-certificates)"; \
    if ! dpkg --compare-versions "$ca_version" ge "$CA_CERTIFICATES_MIN_VERSION"; then \
        echo "ca-certificates ${ca_version} is older than ${CA_CERTIFICATES_MIN_VERSION}" >&2; \
        exit 1; \
    fi

# שדרוג pip לפני ה-pip install הראשון של השלב (ראו PIP_MIN_VERSION למעלה)
RUN PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    python -m pip install --upgrade --no-cache-dir "pip>=${PIP_MIN_VERSION}" 'setuptools>=78.1.1' 'wheel>=0.43.0'

# התקנת תלותי Playwright (root) למנועי Chromium
RUN python -m pip install --no-cache-dir 'playwright==1.49.0' && \
    (python -m playwright install-deps chromium || true)

# התקנת Node בגרסה של NODE_VERSION דרך ארכיון רשמי (מביא npm תואם בלי תלות ב־apt)
RUN set -eux; \
    : "${NODE_VERSION:?NODE_VERSION build arg must be set}"; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
        amd64) node_arch="x64" ;; \
        arm64) node_arch="arm64" ;; \
        armhf) node_arch="armv7l" ;; \
        ppc64el) node_arch="ppc64le" ;; \
        s390x) node_arch="s390x" ;; \
        *) echo "Unsupported architecture for Node.js binaries: ${arch}"; exit 1 ;; \
    esac; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" -o /tmp/node.tar.xz; \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1; \
    rm -f /tmp/node.tar.xz; \
    npm --version; \
    node --version

# ה-driver של Playwright רץ על ה-Node שהותקן כאן, ולא על זה שבתוך החבילה (ב-playwright 1.49.0
# זה 22.11.0, שעוד סומך על "emSign ECC Root CA - G3" — נמדד ב-tls.rootCertificates). המשתנה
# נקרא ב-compute_driver_executable (playwright/_impl/_driver.py), גם ב-python -m playwright
# וגם בהפעלה מהקוד, ולכן הוא ENV שנשאר בזמן ריצה. הוא מוגדר רק אחרי התקנת Node: נתיב
# שעוד לא קיים היה מכשיל את install-deps שלמעלה, וה-|| true שם היה בולע את הכישלון.
ENV PLAYWRIGHT_NODEJS_PATH=/usr/local/bin/node

# יצירת משתמש לא-root (אידמפוטנטי גם כשהקבוצה/המשתמש כבר קיימים)
RUN groupadd -o -f -g 1000 botuser && \
    if ! id -u botuser >/dev/null 2>&1; then \
        useradd -m -s /bin/bash -u 1000 -g botuser botuser 2>/dev/null || \
        useradd -m -s /bin/bash -g botuser botuser; \
    fi && \
    mkdir -p /app /app/logs /app/backups /app/temp && \
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

# הורדת Chromium עבור Playwright למשתמש היישום
RUN python -m playwright install chromium || true

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
