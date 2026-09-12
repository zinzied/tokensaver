import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

export function sha256Hex(data: string | Buffer): string {
  return crypto.createHash('sha256').update(data).digest('hex');
}

export function md5Hex(data: string | Buffer): string {
  return crypto.createHash('md5').update(data).digest('hex');
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function nowIsoUtc(): string {
  return new Date().toISOString();
}

export function isoFromMs(ms: number): string {
  return new Date(ms).toISOString();
}

export function msFromIso(s: string): number {
  return Date.parse(s);
}

export function utcNowMs(): number {
  return Date.now();
}

export function home(): string {
  return os.homedir();
}

export function pathHome(): string {
  return os.homedir();
}

export function join(...parts: string[]): string {
  return path.join(...parts);
}

export function ensureDir(dir: string): void {
  fs.mkdirSync(dir, { recursive: true });
}

export function readJson<T = any>(p: string, fallback: T | null = null): T | null {
  try {
    return JSON.parse(fs.readFileSync(p, 'utf-8')) as T;
  } catch {
    return fallback;
  }
}

export function writeJson(p: string, data: unknown, indent = 2): void {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(data, null, indent) + '\n', 'utf-8');
}

export function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
