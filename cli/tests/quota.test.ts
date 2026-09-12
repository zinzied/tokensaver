import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-quota-'));
process.env.TOKENSAVER_HOME = TMP;

const { QuotaTracker, parse_rate_limit_headers } = await import('../src/core/quota.js');

test('update_quota writes fields and persists to disk', () => {
  const qt = new QuotaTracker();
  qt.update_quota('openai', 'gpt-4o', { total: 10000, used: 1234, remaining: 8766, reset_at: null, account_id: 'acc-1' });
  qt.update_quota('openai', 'gpt-4o', { remaining: 8000, account_id: 'acc-1' });

  const prov = qt.get_quota('openai');
  assert.strictEqual(prov.total_quota, 10000);
  assert.strictEqual(prov.used, 1234);
  assert.strictEqual(prov.remaining, 8000);
  assert.strictEqual(prov.last_model, 'gpt-4o');
  assert.ok(prov.last_checked);

  const reloaded = new QuotaTracker();
  assert.strictEqual(reloaded.get_quota('openai').remaining, 8000);

  const acc = reloaded.get_account('acc-1');
  assert.strictEqual(acc.provider, 'openai');
  assert.strictEqual(acc.remaining, 8000);
  assert.ok(acc.last_used);
});

test('mark_rate_limited / is_rate_limited / clear_rate_limit lifecycle', () => {
  const qt = new QuotaTracker();
  qt.update_quota('deepseek', 'deepseek-chat');
  qt.mark_rate_limited('deepseek', 'deepseek-chat', 5000, 'acc-2');
  assert.strictEqual(qt.is_rate_limited('deepseek'), true);
  assert.strictEqual(qt.is_rate_limited('deepseek', 'acc-2'), true);
  assert.strictEqual(qt.get_quota('deepseek').rate_limited_model, 'deepseek-chat');

  qt.clear_rate_limit('deepseek', 'acc-2');
  assert.strictEqual(qt.is_rate_limited('deepseek'), false);
  assert.strictEqual(qt.is_rate_limited('deepseek', 'acc-2'), false);
});

test('get_reset_countdown formats human readable reset', () => {
  const qt = new QuotaTracker();
  assert.strictEqual(qt.get_reset_countdown('nope'), null);
  qt.update_quota('openai', null, { reset_at: new Date(Date.now() + 65000).toISOString() });
  const cd = qt.get_reset_countdown('openai');
  assert.match(cd!, /^reset in/);
  qt.update_quota('openai', null, { reset_at: new Date(Date.now() - 1000).toISOString() });
  assert.strictEqual(qt.get_reset_countdown('openai'), 'resetting now');
});

test('get_summary aggregates providers with cost and requests', () => {
  const qt = new QuotaTracker();
  qt.log_request('openai', 'gpt-4o', 100, 50, 0.0012);
  qt.log_request('openai', 'gpt-4o', 200, 100, 0.0034);
  qt.mark_rate_limited('glm', 'glm-4', 10000);
  qt.update_quota('glm', 'glm-4', { total: 1000000, remaining: 999000, reset_at: new Date(Date.now() + 10000).toISOString() });

  const summary = qt.get_summary();
  const openai = summary.find((s) => s.provider === 'openai');
  assert.strictEqual(openai!.requests, 2);
  assert.strictEqual(openai!.cost, 0.0046);

  const glm = summary.find((s) => s.provider === 'glm');
  assert.strictEqual(glm!.rate_limited, true);
  assert.strictEqual(glm!.total, 1000000);
  assert.strictEqual(glm!.remaining, 999000);
  assert.match(glm!.reset_in!, /^reset in/);
});

test('parse_rate_limit_headers handles openai and anthropic formats', () => {
  const openai = parse_rate_limit_headers({
    'x-ratelimit-limit-tokens': '200000',
    'x-ratelimit-remaining-tokens': '150000',
    'x-ratelimit-reset-tokens': '30s',
  });
  assert.strictEqual(openai!.remaining, 150000);
  assert.strictEqual(openai!.total, 200000);
  assert.ok(openai!.reset_at);

  const anthropic = parse_rate_limit_headers({
    'anthropic-ratelimit-tokens-limit': '400000',
    'anthropic-ratelimit-tokens-remaining': '250000',
    'anthropic-ratelimit-tokens-reset': '2026-01-01T00:00:00Z',
  });
  assert.strictEqual(anthropic!.remaining, 250000);
  assert.strictEqual(anthropic!.total, 400000);
  assert.ok(anthropic!.reset_at);

  const generic = parse_rate_limit_headers({ 'x-ratelimit-remaining': '42' });
  assert.strictEqual(generic!.remaining, 42);
  assert.strictEqual(generic!.total, null);

  assert.strictEqual(parse_rate_limit_headers(null), null);
  assert.strictEqual(parse_rate_limit_headers({ 'content-type': 'application/json' }), null);
});

test('quota file uses exactly the same schema as python quota_tracker.json', () => {
  const qt = new QuotaTracker();
  qt.update_quota('mistral', 'mistral-large', { remaining: 500, account_id: 'a9' });
  const raw = JSON.parse(fs.readFileSync(path.join(TMP, '.config', 'opencode', 'compress', 'quota_tracker.json'), 'utf8'));
  assert.ok(raw.providers && raw.accounts);
  assert.strictEqual(raw.providers.mistral.last_model, 'mistral-large');
  assert.ok(raw.accounts.a9);
});
