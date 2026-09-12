import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { test } from 'node:test';
import assert from 'node:assert';
import { DatabaseSync } from 'node:sqlite';

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-insights-'));
process.env.TOKENSAVER_HOME = TMP;

const base = path.join(TMP, '.config', 'opencode');
const comp = path.join(base, 'compress');
fs.mkdirSync(comp, { recursive: true });

const now = new Date().toISOString();
const ledger = [
  {
    timestamp: now,
    kind: 'file_read',
    description: 'map:token-saver.py',
    raw_tokens: 50000,
    compressed_tokens: 13,
    saved_tokens: 49987,
    compression_pct: 99.9,
    metadata: { file: 'token-saver.py', mode: 'map' },
  },
  {
    timestamp: new Date(Date.now() - 1000).toISOString(),
    kind: 'shell',
    description: 'git status:git status',
    raw_tokens: 25,
    compressed_tokens: 8,
    saved_tokens: 17,
    compression_pct: 68,
    metadata: {},
  },
];
fs.writeFileSync(path.join(comp, 'savings_ledger.json'), JSON.stringify(ledger));

fs.writeFileSync(
  path.join(comp, 'proxy.json'),
  JSON.stringify({
    enabled: true,
    port: 8199,
    total_saved_tokens: 1000,
    total_saved_bytes: 5000,
    proxied_providers: ['openai', 'openrouter'],
    upstreams: { openai: 'https://api.openai.com/v1', openrouter: 'https://openrouter.ai/api/v1' },
    history: [
      { path: '/v1/chat/completions', model: 'openai/gpt-x', saved_tokens: 120, timestamp: 1750000000 },
      { path: '/v1/chat/completions', model: 'openrouter/other', saved_bytes: 300, timestamp: 1750000001 },
    ],
  })
);

fs.writeFileSync(
  path.join(comp, 'quota_tracker.json'),
  JSON.stringify({
    providers: { 'test-provider': { total_quota: 5000, remaining: 1000, last_checked: now } },
    accounts: {},
  })
);

fs.writeFileSync(
  path.join(comp, 'budget.json'),
  JSON.stringify({
    task: 'fix the login bug',
    task_tokens: 9,
    budget_limit: 8000,
    allocation: { file_reads: 2800, shell_commands: 1200 },
    total_allocated: 4000,
    remaining: 500,
  })
);

fs.writeFileSync(
  path.join(comp, 'fallback.json'),
  JSON.stringify({ 'openai/gpt-x': ['openrouter/other', 'openai/gpt-y'] })
);

fs.writeFileSync(
  path.join(base, 'opencode.jsonc'),
  JSON.stringify({
    model: 'openai/gpt-x',
    small_model: 'openai/small',
    provider: { openai: { options: { baseURL: 'https://api.openai.com/v1' } } },
  })
);

const db = new DatabaseSync(path.join(comp, 'index.db'));
db.exec(`create table events (
  id text primary key, session_id text, kind text, description text,
  raw_tokens int, compressed_tokens int, saved_tokens int, compression_pct real,
  metadata text, timestamp text, hash text, prev_hash text
)`);
db.exec(`create table proxy_requests (
  id int primary key, path text, model text, cost_level text,
  raw_tokens int, saved_tokens int, timestamp text
)`);
db.exec(`create table files_touched (
  event_id text, path text, mode text, compression_pct real, cached int
)`);
db.prepare(
  'insert into events (id, session_id, kind, description, raw_tokens, compressed_tokens, saved_tokens, compression_pct, metadata, timestamp, hash, prev_hash) values (?,?,?,?,?,?,?,?,?,?,?,?)'
).run('evt_1', null, 'file_read', 'map:token-saver.py', 50000, 13, 49987, 99.9, '{}', now, 'h', 'p');
db.prepare(
  'insert into events (id, session_id, kind, description, raw_tokens, compressed_tokens, saved_tokens, compression_pct, metadata, timestamp, hash, prev_hash) values (?,?,?,?,?,?,?,?,?,?,?,?)'
).run('evt_2', null, 'shell', 'git status:git status', 25, 8, 17, 68.0, '{}', now, 'h2', 'p2');
db.prepare(
  'insert into proxy_requests (id, path, model, cost_level, raw_tokens, saved_tokens, timestamp) values (?,?,?,?,?,?,?)'
).run(1, '/v1/chat/completions', 'openai/gpt-x', '', 0, 120, now);
db.close();

const insights = await import('../src/core/insights.js');

test('usageSummary aggregates ledger + proxy history', () => {
  const u = insights.usageSummary();
  assert.strictEqual(u.ledger.entries, 2);
  assert.strictEqual(u.ledger.saved_tokens, 50004);
  assert.strictEqual(u.ledger.raw_tokens, 50025);
  assert.strictEqual(u.proxy.requests, 2);
  assert.strictEqual(u.proxy.saved_tokens, 1120);
  assert.strictEqual(u.proxy.saved_bytes, 5300);
  const fileRead = u.byKind.find((k: any) => k.kind === 'file_read');
  assert.strictEqual(fileRead!.saved_tokens, 49987);
  assert.strictEqual(u.perModel.length, 2);
});

test('quotaSummary returns tracker + budget', () => {
  const q = insights.quotaSummary();
  assert.strictEqual(q.quota.providers['test-provider'].remaining, 1000);
  assert.strictEqual(q.budget.budget_limit, 8000);
  assert.strictEqual(q.budget.remaining, 500);
});

test('routingSummary resolves current model, upstream and fallback chain', () => {
  const r = insights.routingSummary();
  assert.strictEqual(r.currentModel, 'openai/gpt-x');
  assert.ok(r.upstream);
  assert.deepStrictEqual(r.fallbackChain, ['openrouter/other', 'openai/gpt-y']);
  const openai = r.routing.find((x: any) => x.provider === 'openai');
  assert.ok(openai!.proxied);
  assert.ok(openai!.configured);
  assert.ok(openai!.baseURL);
  assert.ok(r.tier);
  assert.ok(Array.isArray(r.tieredChain));
  assert.ok(Array.isArray(r.accounts));
  assert.ok(r.accountStrategy);
});

test('providersList merges configured + proxied providers', () => {
  const list = insights.providersList();
  const openai = list.find((p: any) => p.provider === 'openai');
  assert.ok(openai);
  assert.ok(openai.configured);
  assert.strictEqual(openai.baseURL, 'https://api.openai.com/v1');
  const openrouter = list.find((p: any) => p.provider === 'openrouter');
  assert.ok(openrouter!.proxied);
});

test('searchQuery finds ledger, index events and proxy requests', () => {
  const hits = insights.searchQuery('token-saver');
  assert.ok(hits.length >= 2);
  const descs = hits.map((h: any) => `${h.source}:${h.description || ''}`);
  assert.ok(descs.some((d: string) => d.includes('event')));
  assert.ok(descs.some((d: string) => d.includes('ledger')));
  const reqs = insights.searchQuery('gpt-x');
  assert.ok(reqs.some((h: any) => h.source === 'request' && h.model === 'openai/gpt-x'));
  assert.deepStrictEqual(insights.searchQuery(''), []);
});

test('compressTest detects git diff and reports savings', () => {
  const block = [
    'diff --git a/src/main.rs b/src/main.rs',
    'index 1234567..89abcde 100644',
    '--- a/src/main.rs',
    '+++ b/src/main.rs',
    '@@ -10,7 +10,7 @@ fn main() {',
    '-    let old = 1;',
    '+    let new = 2;',
    '     println!("hi");',
    ' }',
    'diff --git a/README.md b/README.md',
    'new file mode 100644',
    '--- /dev/null',
    '+++ b/README.md',
    '@@ -0,0 +1,5 @@',
    '# Hello',
    'line1',
    'line2',
    'line3',
    'line4',
  ].join('\n');
  const diff = Array(4).fill(block).join('\n') + '\n';
  const r = insights.compressTest(diff);
  assert.strictEqual(r.detected, 'git_diff');
  assert.ok(r.saved > 0);
  assert.ok(r.pct > 0);
  assert.ok(r.compressed);

  const small = insights.compressTest('hi');
  assert.ok(small.tooSmall);
  assert.strictEqual(small.detected, null);
});

test('settingsGet reads config and lists backups', () => {
  const s = insights.settingsGet();
  assert.strictEqual(s.model, 'openai/gpt-x');
  assert.strictEqual(s.small_model, 'openai/small');
  assert.strictEqual(s.current, 'openai/gpt-x');
  assert.ok(s.path.includes('opencode.jsonc'));
  assert.ok(Array.isArray(s.backups));
});
