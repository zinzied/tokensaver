import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-config-'));
process.env.TOKENSAVER_HOME = tmp;

const config = await import('../src/core/config.js');

test('strip_jsonc strips // and /* */ comments', () => {
  const input = `{\n  // line comment\n  "a": "http://example.com", /* block */\n  "b": 1, // trailing\n}`;
  const out = config.strip_jsonc(input);
  assert.ok(out.includes('"a": "http://example.com"'));
  assert.ok(!out.includes('// line comment'));
  assert.ok(!out.includes('/* block */'));
  // Python's regex `^\s*//.*` only strips full-line comments, not trailing ones.
  assert.ok(out.includes('// trailing'));
});

test('read_config returns null when missing and parses JSONC when present', () => {
  assert.strictEqual(config.read_config(), null);
  fs.mkdirSync(path.dirname(config.CONFIG_PATH), { recursive: true });
  fs.writeFileSync(
    config.CONFIG_PATH,
    '{\n  // comment\n  "model": "provider/model",\n  "provider": {}\n}\n',
    'utf-8'
  );
  const cfg = config.read_config();
  assert.strictEqual(cfg!.model, 'provider/model');
  assert.deepStrictEqual(cfg!.provider, {});
});

test('read_config handles UTF-8 BOM', () => {
  const bom = '\uFEFF' + '{\n  "model": "bom/model"\n}\n';
  fs.writeFileSync(config.CONFIG_PATH, bom, 'utf-8');
  const cfg = config.read_config();
  assert.strictEqual(cfg!.model, 'bom/model');
});

test('write_config writes model + compaction + provider and rotates backup', () => {
  const cfgPath = config.CONFIG_PATH;
  fs.writeFileSync(cfgPath, '{\n  "model": "old/m",\n  "provider": {}\n}\n', 'utf-8');
  config.write_config('new/model', 'new/small');
  const cfg = config.read_config();
  assert.strictEqual(cfg!.model, 'new/model');
  assert.strictEqual(cfg!.small_model, 'new/small');
  assert.deepStrictEqual(cfg!.compaction, { auto: true, prune: true, reserved: 10000 });
  const backups = config.list_backups();
  assert.ok(backups.length >= 1, 'backup should exist after write_config');
});

test('rotate_backup keeps at most MAX_BACKUPS backups', () => {
  const dir = config.BACKUP_DIR;
  for (let i = 0; i < config.MAX_BACKUPS + 2; i++) {
    fs.writeFileSync(
      path.join(dir, `opencode.jsonc.2024010${i}_00000${i}.backup`),
      '{}',
      'utf-8'
    );
  }
  config.rotate_backup();
  const count = fs.readdirSync(dir).filter((n) => n.endsWith('.backup')).length;
  assert.ok(count <= config.MAX_BACKUPS + 1, `got ${count} backups`);
});

test('paths live under ~/.config/opencode', () => {
  assert.strictEqual(config.COMPRESS_DIR, path.join(tmp, '.config', 'opencode', 'compress'));
  assert.ok(fs.existsSync(config.COMPRESS_DIR));
  assert.ok(fs.existsSync(config.CONTENT_CACHE));
  assert.ok(fs.existsSync(config.CONTENT_STORE));
});
