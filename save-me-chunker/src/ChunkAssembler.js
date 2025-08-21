import { computeSha256, fromBase64, gunzipBuffer, writeFileSafe } from './utils.js';
import path from 'path';
import { parseProtocolMessage } from './ChunkProtocol.js';

export class ChunkAssembler {
  constructor(options) {
    const { rootDir, sessionTtlMs = 15 * 60 * 1000 } = options || {};
    if (!rootDir) throw new Error('rootDir is required');
    this.rootDir = path.resolve(rootDir);
    this.sessionTtlMs = sessionTtlMs;
    this.sessions = new Map(); // key: chatKey + '::' + id -> session
  }

  _key(chatKey, id) {
    return `${chatKey}::${id}`;
  }

  _gc() {
    const now = Date.now();
    for (const [k, s] of this.sessions.entries()) {
      if (now - s.createdAt > this.sessionTtlMs) {
        this.sessions.delete(k);
      }
    }
  }

  onMessage(rawText, chatKey) {
    this._gc();
    const msg = parseProtocolMessage(rawText);
    if (!msg) return null;
    if (msg.type === 'error') return { ok: false, error: msg.error };

    if (msg.type === 'start') {
      if (!msg.meta.path) return { ok: false, error: 'missing path' };
      if (msg.meta.encoding !== 'base64') return { ok: false, error: 'unsupported encoding' };
      if (!['none', 'gzip'].includes(msg.meta.compression)) return { ok: false, error: 'unsupported compression' };

      const session = {
        id: msg.id,
        path: msg.meta.path,
        total: msg.meta.total_parts,
        encoding: msg.meta.encoding,
        compression: msg.meta.compression,
        sha256: msg.meta.sha256,
        createdAt: Date.now(),
        received: new Map(), // index -> base64 string
      };
      this.sessions.set(this._key(chatKey, msg.id), session);
      return { ok: true, stage: 'start', id: msg.id, total: session.total };
    }

    if (msg.type === 'chunk') {
      const key = this._key(chatKey, msg.id);
      const session = this.sessions.get(key);
      if (!session) return { ok: false, error: 'no active session for id' };
      if (msg.total !== session.total) return { ok: false, error: 'total mismatch' };
      if (msg.index < 1 || msg.index > session.total) return { ok: false, error: 'index out of range' };
      session.received.set(msg.index, msg.dataB64);
      return { ok: true, stage: 'chunk', id: msg.id, index: msg.index, receivedCount: session.received.size, total: session.total };
    }

    if (msg.type === 'end') {
      const key = this._key(chatKey, msg.id);
      const session = this.sessions.get(key);
      if (!session) return { ok: false, error: 'no active session for id' };

      // Validate completeness
      if (session.received.size !== session.total) {
        const missing = [];
        for (let i = 1; i <= session.total; i++) {
          if (!session.received.has(i)) missing.push(i);
        }
        return { ok: false, error: 'missing chunks', missing };
      }

      // Concatenate base64 strings in order
      const ordered = [];
      for (let i = 1; i <= session.total; i++) {
        ordered.push(session.received.get(i));
      }
      const joinedB64 = ordered.join('');
      let data = fromBase64(joinedB64);
      if (session.compression === 'gzip') {
        data = gunzipBuffer(data);
      }

      if (session.sha256) {
        const actual = computeSha256(data);
        if (actual !== session.sha256) {
          return { ok: false, error: 'sha256 mismatch', expected: session.sha256, actual };
        }
      }

      const savedPath = writeFileSafe(this.rootDir, session.path, data);
      this.sessions.delete(key);
      return { ok: true, stage: 'end', id: session.id, path: savedPath, bytes: data.length };
    }

    if (msg.type === 'cancel') {
      const key = this._key(chatKey, msg.id);
      const existed = this.sessions.delete(key);
      return { ok: true, stage: 'cancel', id: msg.id, existed };
    }

    return { ok: false, error: 'unsupported message type' };
  }
}