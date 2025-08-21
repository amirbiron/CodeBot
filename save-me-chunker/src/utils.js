import fs from 'fs';
import path from 'path';
import { createHash, randomUUID } from 'crypto';
import zlib from 'zlib';

export function computeSha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

export function gzipBuffer(buffer) {
  return zlib.gzipSync(buffer);
}

export function gunzipBuffer(buffer) {
  return zlib.gunzipSync(buffer);
}

export function toBase64(buffer) {
  return buffer.toString('base64');
}

export function fromBase64(base64String) {
  return Buffer.from(base64String, 'base64');
}

export function ensureDirSync(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

export function writeFileSafe(rootDir, relativeTargetPath, dataBuffer) {
  const resolvedRoot = path.resolve(rootDir);
  const resolvedTarget = path.resolve(resolvedRoot, relativeTargetPath);
  if (!resolvedTarget.startsWith(resolvedRoot + path.sep) && resolvedTarget !== resolvedRoot) {
    throw new Error(`Path traversal detected: ${relativeTargetPath}`);
  }
  ensureDirSync(path.dirname(resolvedTarget));
  fs.writeFileSync(resolvedTarget, dataBuffer);
  return resolvedTarget;
}

export function stripCodeFences(text) {
  // Remove surrounding triple backticks if present
  const fenceRegex = /^```[\s\S]*?\n([\s\S]*?)\n```\s*$/;
  const match = text.match(fenceRegex);
  if (match) return match[1];
  return text;
}

export function normalizeNewlines(text) {
  return text.replace(/\r\n?/g, '\n');
}

export function genId() {
  try {
    return randomUUID();
  } catch (_) {
    // Fallback simple random id
    return 'id-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
}