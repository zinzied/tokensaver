import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { test } from 'node:test';
import assert from 'node:assert';

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-index-'));
process.env.TOKENSAVER_HOME = TMP;

const index = await import('../src/core/index.js');

test('logProxyRequest inserts rows and proxyStats aggregates them', () => {
  assert.strictEqual(index.logProxyRequest('/v1/chat/completions', 'openai/gpt-4o', 1000, 250), true);
  assert.strictEqual(index.logProxyRequest('/v1/chat/completions', 'openai/gpt-4o', 2000, 500), true);

  const stats = index.proxyStats();
  assert.strictEqual(stats!.total_requests, 2);
  assert.strictEqual(stats!.total_saved, 750);
  assert.ok(stats!.avg_saved > 0);

  const dbFile = path.join(TMP, '.config', 'opencode', 'compress', 'index.db');
  assert.ok(fs.existsSync(dbFile));
});
