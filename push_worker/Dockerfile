# Minimal Node image for push-delivery-worker
FROM node:20-alpine

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
