import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { test } from 'node:test';
import assert from 'node:assert';

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-routing-'));
process.env.TOKENSAVER_HOME = TMP;

const routing = await import('../src/core/routing.js');

test('get_quota_cooldown follows exponential backoff with clamp', () => {
  assert.strictEqual(routing.get_quota_cooldown(0), 2000);
  assert.strictEqual(routing.get_quota_cooldown(1), 2000);
  assert.strictEqual(routing.get_quota_cooldown(2), 4000);
  assert.strictEqual(routing.get_quota_cooldown(3), 8000);
  assert.strictEqual(routing.get_quota_cooldown(50), 300000);
});

test('check_fallback_error matches text and status rules', () => {
  const rate = routing.check_fallback_error(200, 'rate limit exceeded', 3);
  assert.strictEqual(rate.should_fallback, true);
  assert.strictEqual(rate.new_backoff_level, 4);
  assert.strictEqual(rate.cooldown_ms, routing.get_quota_cooldown(4));

  const quota = routing.check_fallback_error(200, 'You have exceeded your quota');
  assert.strictEqual(quota.should_fallback, true);
  assert.ok(quota.cooldown_ms > 0);

  const bad = routing.check_fallback_error(401, 'no credentials here');
  assert.strictEqual(bad.cooldown_ms, routing.COOLDOWN_LONG_MS);

  const err = routing.check_fallback_error(429, '');
  assert.strictEqual(err.new_backoff_level, 1);
  assert.strictEqual(err.cooldown_ms, 2000);

  const generic = routing.check_fallback_error(500, 'something exploded');
  assert.strictEqual(generic.cooldown_ms, routing.TRANSIENT_COOLDOWN_MS);
});

test('tier helpers resolve provider tiers and fallback chains', () => {
  assert.strictEqual(routing.get_tier_for_provider('glm'), 'cheap');
  assert.strictEqual(routing.get_tier_for_provider('claude-code'), 'subscription');
  assert.strictEqual(routing.get_tier_for_provider('unknown-xyz'), 'free');
  assert.ok(routing.get_providers_in_tier('free').kiro);
  assert.strictEqual(routing.get_provider_endpoint('glm').format, 'openai');
  const chain = routing.resolve_fallback_chain('glm');
  assert.deepStrictEqual(chain, ['kiro', 'opencode-free', 'vertex', 'iflow', 'qwen']);
});

test('AccountManager persists accounts and honors rate limiting', () => {
  const am = new routing.AccountManager();
  const a1 = am.add_account('openai', 'key-1', 'https://api.openai.com/v1', 0);
  const a2 = am.add_account('openai', 'key-2', null, 0);
  assert.strictEqual(a1, 'openai_0');
  assert.strictEqual(a2, 'openai_1');

  assert.strictEqual(am.select_account('openai')!.id, a1);
  assert.strictEqual(am.select_account('openai', 'round-robin')!.id, a1);
  assert.strictEqual(am.select_account('openai', 'round-robin')!.id, a2);

  am.mark_error(a1, 429, '');
  assert.ok(am.get_active_accounts('openai').every((a) => a.id !== a1));

  const reloaded = new routing.AccountManager();
  assert.strictEqual(reloaded.get_active_accounts('openai').length, 1);
  assert.strictEqual(reloaded.get_active_accounts('openai')[0].id, a2);

  const summary = am.get_summary();
  assert.strictEqual(summary.find((s) => s.id === a1)!.status, 'rate_limited');
  assert.strictEqual(summary.find((s) => s.id === a2)!.status, 'active');

  am.mark_success(a1);
  assert.strictEqual(am.get_active_accounts('openai').length, 2);

  assert.strictEqual(am.select_account('missing-provider'), null);
});

test('TieredRouter builds model chain and rotates accounts', () => {
  const am = new routing.AccountManager();
  const router = new routing.TieredRouter(am);
  assert.strictEqual(router.get_tier_for_provider('minimax'), 'cheap');
  assert.deepStrictEqual(router.build_fallback_chain('glm'), [
    'minimax',
    'kimi',
    'kiro',
    'opencode-free',
    'vertex',
    'iflow',
    'qwen',
  ]);
  assert.deepStrictEqual(router.build_fallback_chain('kiro'), [
    'opencode-free',
    'vertex',
    'iflow',
    'qwen',
  ]);
  const chain = router.resolve_model_chain('glm', null, ['glm', 'extra-model']);
  assert.strictEqual(chain[0], 'glm');
  assert.ok(chain.includes('extra-model'));

  am.add_account('router-proxy', 'k1');
  am.add_account('router-proxy', 'k2');
  const [id1, acc1] = router.try_account('router-proxy', 'round-robin', 'router-proxy/m');
  const [id2] = router.try_account('router-proxy', 'round-robin', 'router-proxy/m');
  assert.ok(id1 && id2);
  assert.notStrictEqual(id1, id2);
  assert.strictEqual(acc1!.api_key, 'k1');
  const [missingId, missingAcc] = router.try_account('nobody');
  assert.strictEqual(missingId, null);
  assert.strictEqual(missingAcc, null);
});
