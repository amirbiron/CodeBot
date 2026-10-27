# Minimal Node image for push-delivery-worker
# גרסה מדויקת ולא node:22-alpine, כמו NODE_VERSION ב-Dockerfile הראשי. לקו 20 שהיה כאן אין
# גרסה שמתקנת את אירוע eMudhra (סוף החיים שלו היה ב-30.4.2026) — ראו ההערה שם.
FROM node:22.23.4-alpine

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm install --omit=dev && npm cache clean --force

# Copy source
COPY index.js ./

# Security: run as non-root
USER node

ENV PORT=8080
EXPOSE 8080

CMD ["node", "index.js"]
