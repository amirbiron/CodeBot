import { normalizeNewlines, stripCodeFences } from './utils.js';

// Message formats:
// [FILE START]\n
// id=<uuid>\n
// path=<dst/relative.ext>\n
// total_parts=<N>\n
// encoding=base64\n
// compression=<none|gzip>\n
// sha256=<hash>
//
// [FILE CHUNK i/N id=<uuid>]\n
// <base64 data>
//
// [FILE END id=<uuid>]
// [FILE CANCEL id=<uuid>]

const START_HEADER = '[FILE START]';
const END_PREFIX = '[FILE END';
const CANCEL_PREFIX = '[FILE CANCEL';
const CHUNK_PREFIX = '[FILE CHUNK';

export function parseProtocolMessage(rawText) {
  if (!rawText || typeof rawText !== 'string') return null;
  let text = normalizeNewlines(stripCodeFences(rawText)).trim();

  if (text.startsWith(START_HEADER)) {
    const body = text.slice(START_HEADER.length).trim();
    const meta = parseKeyValueBody(body);
    if (!meta.id) return { type: 'error', error: 'missing id in START' };
    const total = parseInt(meta.total_parts, 10);
    if (!Number.isFinite(total) || total <= 0) return { type: 'error', error: 'invalid total_parts' };
    const encoding = (meta.encoding || 'base64').toLowerCase();
    const compression = (meta.compression || 'none').toLowerCase();
    return {
      type: 'start',
      id: meta.id,
      meta: {
        path: meta.path,
        total_parts: total,
        encoding,
        compression,
        sha256: meta.sha256 || null,
      },
    };
  }

  if (text.startsWith(CHUNK_PREFIX)) {
    // [FILE CHUNK i/N id=<uuid>]\n<base64>
    const headerMatch = text.match(/^\[FILE CHUNK\s+(\d+)\s*\/\s*(\d+)\s+id=([^\]]+)\]\s*\n([\s\S]*)$/);
    if (!headerMatch) return { type: 'error', error: 'invalid CHUNK header' };
    const index = parseInt(headerMatch[1], 10);
    const total = parseInt(headerMatch[2], 10);
    const id = headerMatch[3].trim();
    const data = headerMatch[4].trim();
    return { type: 'chunk', id, index, total, dataB64: data };
  }

  if (text.startsWith(END_PREFIX)) {
    const m = text.match(/^\[FILE END\s+id=([^\]]+)\]\s*$/);
    if (!m) return { type: 'error', error: 'invalid END header' };
    return { type: 'end', id: m[1].trim() };
  }

  if (text.startsWith(CANCEL_PREFIX)) {
    const m = text.match(/^\[FILE CANCEL\s+id=([^\]]+)\]\s*$/);
    if (!m) return { type: 'error', error: 'invalid CANCEL header' };
    return { type: 'cancel', id: m[1].trim() };
  }

  return null;
}

function parseKeyValueBody(body) {
  const meta = {};
  const lines = body.split(/\n+/).map((s) => s.trim()).filter(Boolean);
  for (const line of lines) {
    const eqIdx = line.indexOf('=');
    if (eqIdx === -1) continue;
    const key = line.slice(0, eqIdx).trim();
    const value = line.slice(eqIdx + 1).trim();
    meta[key] = value;
  }
  return meta;
}

export function formatStart({ id, path, total_parts, encoding = 'base64', compression = 'none', sha256 = null }) {
  let out = `${START_HEADER}\n`;
  out += `id=${id}\n`;
  out += `path=${path}\n`;
  out += `total_parts=${total_parts}\n`;
  out += `encoding=${encoding}\n`;
  out += `compression=${compression}\n`;
  if (sha256) out += `sha256=${sha256}\n`;
  return out.trim();
}

export function formatChunk({ id, index, total, dataB64 }) {
  return `[FILE CHUNK ${index}/${total} id=${id}]\n${dataB64}`;
}

export function formatEnd({ id }) {
  return `[FILE END id=${id}]`;
}

export function formatCancel({ id }) {
  return `[FILE CANCEL id=${id}]`;
}