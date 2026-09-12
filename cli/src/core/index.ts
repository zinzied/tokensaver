import { createRequire } from 'node:module';
import { INDEX_DB_PATH } from './config.js';
import type { SqliteDb } from './types.js';

const require = createRequire(import.meta.url);

let _db: SqliteDb | null = null;

function _init(db: SqliteDb): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS proxy_requests (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        path        TEXT,
        model       TEXT,
        cost_level  TEXT,
        raw_tokens  INTEGER DEFAULT 0,
        saved_tokens INTEGER DEFAULT 0,
        timestamp   TEXT NOT NULL
    )
  `);
}

function _open(): SqliteDb | null {
  if (_db) return _db;
  try {
    const Database = require('better-sqlite3');
    _db = new Database(INDEX_DB_PATH) as SqliteDb;
    _init(_db);
    return _db;
  } catch {}
  try {
    const { DatabaseSync } = require('node:sqlite');
    _db = new DatabaseSync(INDEX_DB_PATH) as unknown as SqliteDb;
    _init(_db);
    return _db;
  } catch {
    return null;
  }
}

export function logProxyRequest(path: string, model: string, rawTokens = 0, savedTokens = 0, costLevel = ''): boolean {
  const db = _open();
  if (!db) return false;
  try {
    db.prepare(
      'INSERT INTO proxy_requests (path, model, cost_level, raw_tokens, saved_tokens, timestamp) VALUES (?, ?, ?, ?, ?, ?)'
    ).run(path, model, costLevel, rawTokens, savedTokens, new Date().toISOString());
    return true;
  } catch {
    return false;
  }
}

export function proxyStats(): { total_requests: number; total_saved: number; avg_saved: number } | null {
  const db = _open();
  if (!db) return null;
  try {
    const row = db
      .prepare(
        'SELECT COUNT(*) AS total_requests, COALESCE(SUM(saved_tokens),0) AS total_saved, COALESCE(AVG(saved_tokens),0) AS avg_saved FROM proxy_requests'
      )
      .get() as { total_requests: number; total_saved: number; avg_saved: number } | undefined;
    return row || null;
  } catch {
    return null;
  }
}
