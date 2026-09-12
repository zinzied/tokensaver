import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-insights-'));
process.env.TOKENSAVER_HOME = TMP;

const proxy = await import('../src/core/proxy.js');

function bigDiff() {
  return Array.from(
    { length: 30 },
    (_, i) =>
      `diff --git a/file${i}.js b/file${i}.js\n--- a/file${i}.js\n+++ b/file${i}.js\n@@ -1,2 +1,2 @@\n-old line ${i}\n+new line ${i}\n`
  ).join('');
}

function listen(server: http.Server): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve((server.address() as any).port));
  });
}

function post(port: number, pathname: string, body: string): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(body);
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        path: pathname,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': data.length },
      },
      (res) => {
        let chunks = '';
        res.on('data', (c) => (chunks += c));
        res.on('end', () => resolve({ status: res.statusCode!, body: chunks }));
      }
    );
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

test('canonicalEndpoint normalizes /v1 paths', () => {
  assert.strictEqual(proxy.canonicalEndpoint('/v1/chat/completions'), '/chat/completions');
  assert.strictEqual(proxy.canonicalEndpoint('/chat/completions'), '/chat/completions');
  assert.strictEqual(proxy.canonicalEndpoint('/v1/responses'), '/responses');
  assert.strictEqual(proxy.canonicalEndpoint('/v1/messages'), '/messages');
  assert.strictEqual(proxy.canonicalEndpoint('/v1/models'), '/models');
  assert.strictEqual(proxy.canonicalEndpoint('/v1/embeddings'), '/v1/embeddings');
});

test('resolveUpstream routes model prefix to its provider base', () => {
  proxy.saveConfig({ port: 0, enabled: false, saved_base_urls: { openai: 'https://api.openai.com/v1' } });
  const r = proxy.resolveUpstream('openai/gpt-4o', '/v1/chat/completions');
  assert.strictEqual(r.pid, 'openai');
  assert.strictEqual(r.url, 'https://api.openai.com/v1/chat/completions');
});

test('resolveUpstream falls back to defaults for unknown models', () => {
  proxy.saveConfig({ port: 0, enabled: false });
  const r = proxy.resolveUpstream('unknown-model-x', '/v1/responses');
  assert.strictEqual(r.url, 'https://api.openai.com/v1/responses');
});

test('resolveUpstream routes bare catalog models to their provider', () => {
  const cfgDir = path.join(TMP, '.config', 'opencode');
  fs.mkdirSync(cfgDir, { recursive: true });
  fs.writeFileSync(
    path.join(cfgDir, 'models_cache.json'),
    JSON.stringify({ opencode: { name: 'OpenCode', models: { 'big-pickle': {} } } }),
    'utf-8'
  );
  proxy.saveConfig({
    port: 0,
    enabled: false,
    proxied_providers: ['opencode'],
    saved_base_urls: { opencode: 'https://opencode.ai/zen/v1' },
  });
  const r = proxy.resolveUpstream('big-pickle', '/v1/chat/completions');
  assert.strictEqual(r.pid, 'opencode');
  assert.strictEqual(r.url, 'https://opencode.ai/zen/v1/chat/completions');
});

test('enable writes config and status reports running state', async () => {
  proxy.saveConfig({ port: 0, enabled: false });
  const cfg = proxy.enable(true, 9999);
  assert.strictEqual(cfg.enabled, true);
  assert.strictEqual(cfg.port, 9999);
  const st = proxy.status();
  assert.strictEqual(st.enabled, true);
  assert.strictEqual(st.running, false);
});

test('proxy compresses outgoing tool results', async () => {
  let receivedBody: string | null = null;
  const mock = http.createServer((req, res) => {
    let chunks = '';
    req.on('data', (c) => (chunks += c));
    req.on('end', () => {
      receivedBody = chunks;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({ id: 'x', object: 'chat.completion', choices: [{ message: { role: 'assistant', content: 'ok' } }] })
      );
    });
  });
  const mockPort = await listen(mock);
  proxy.saveConfig({ port: 0, enabled: false, saved_base_urls: { openai: `http://127.0.0.1:${mockPort}/v1` } });

  const toolResult = bigDiff();
  const body = JSON.stringify({
    model: 'openai/gpt-4o',
    messages: [
      { role: 'user', content: 'run the tests' },
      { role: 'assistant', content: 'on it' },
      { role: 'tool', content: toolResult },
    ],
  });

  await proxy.start(0);
  try {
    const s = await post(proxy.status().port!, '/v1/chat/completions', body);
    assert.strictEqual(s.status, 200);
    assert.ok(JSON.parse(s.body).id === 'x');
    const parsed = JSON.parse(receivedBody!);
    assert.ok(parsed.messages[2].content.length < toolResult.length);
    const st = proxy.status();
    assert.strictEqual(st.requestsServed, 1);
    assert.strictEqual(st.compressionHits, 1);
    assert.ok(st.totalSavedBytes > 0);
  } finally {
    await proxy.stop();
    mock.close();
  }
});

test('proxy retries with original body when upstream returns 400', async () => {
  let calls = 0;
  const bodies: string[] = [];
  const mock = http.createServer((req, res) => {
    let chunks = '';
    req.on('data', (c) => (chunks += c));
    req.on('end', () => {
      calls += 1;
      bodies.push(chunks);
      if (calls === 1) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: { message: 'bad request' } }));
      } else {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ id: 'retried', choices: [] }));
      }
    });
  });
  const mockPort = await listen(mock);
  proxy.saveConfig({ port: 0, enabled: false, saved_base_urls: { openai: `http://127.0.0.1:${mockPort}/v1` } });

  const toolResult = bigDiff();
  const body = JSON.stringify({ model: 'openai/gpt-4o', messages: [{ role: 'tool', content: toolResult }] });

  await proxy.start(0);
  try {
    const s = await post(proxy.status().port!, '/v1/chat/completions', body);
    assert.strictEqual(s.status, 200);
    assert.strictEqual(calls, 2);
    assert.ok(bodies[0].length < body.length);
    assert.strictEqual(bodies[1], body);
  } finally {
    await proxy.stop();
    mock.close();
  }
});

test('testConnection reports health and upstream forwarding', async () => {
  const mock = http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/v1/models') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ data: [{ id: 'm' }] }));
      return;
    }
    res.writeHead(404);
    res.end();
  });
  const mockPort = await listen(mock);
  proxy.saveConfig({ port: 0, enabled: false, saved_base_urls: { openai: `http://127.0.0.1:${mockPort}/v1` } });

  const idle = await proxy.testConnection();
  assert.strictEqual(idle.running, false);

  await proxy.start(0);
  try {
    const t = await proxy.testConnection();
    assert.strictEqual(t.running, true);
    assert.ok(t.port! > 0);
    assert.strictEqual(t.health!.ok, true);
    assert.strictEqual(t.health!.code, 200);
    assert.ok(t.forward);
    assert.strictEqual(t.forward.code, 200);
    assert.ok(t.forward.upstream.includes('127.0.0.1'));
  } finally {
    await proxy.stop();
    mock.close();
  }
});

test('proxy records python-style saved_tokens and writes index rows', async () => {
  const mock = http.createServer((req, res) => {
    req.resume();
    req.on('end', () => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ id: 'x', choices: [] }));
    });
  });
  const mockPort = await listen(mock);
  proxy.saveConfig({ port: 0, enabled: false, saved_base_urls: { openai: `http://127.0.0.1:${mockPort}/v1` } });

  const toolResult = bigDiff();
  const body = JSON.stringify({
    model: 'openai/gpt-4o',
    messages: [{ role: 'user', content: 'go' }, { role: 'tool', content: toolResult }],
  });

  await proxy.start(0);
  try {
    const s = await post(proxy.status().port!, '/v1/chat/completions', body);
    assert.strictEqual(s.status, 200);

    const cfg = proxy.loadConfig();
    const entry = cfg.history![cfg.history!.length - 1];
    assert.ok(entry.saved_tokens! > 0, 'expected saved_tokens > 0');
    assert.strictEqual(entry.frost_saved, 0);
    assert.ok(typeof entry.timestamp === 'number');
    assert.strictEqual(cfg.total_saved_tokens, entry.saved_tokens);

    const index = await import('../src/core/index.js');
    const stats = index.proxyStats();
    assert.ok(stats!.total_requests >= 1);
    assert.ok(stats!.total_saved >= entry.saved_tokens!);
  } finally {
    await proxy.stop();
    mock.close();
  }
});

test('proxy rotates accounts and overrides auth + base url', async () => {
  const seen: any[] = [];
  const mock = http.createServer((req, res) => {
    let chunks = '';
    req.on('data', (c) => (chunks += c));
    req.on('end', () => {
      seen.push({ auth: req.headers.authorization, body: chunks, count: seen.length + 1 });
      if (seen.length === 1) {
        res.writeHead(429, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: { message: 'rate limit' } }));
      } else {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ id: 'ok' }));
      }
    });
  });
  const mockPort = await listen(mock);
  proxy.saveConfig({
    port: 0,
    enabled: false,
    saved_base_urls: { openai: `http://127.0.0.1:${mockPort}/v1` },
    account_strategy: 'round-robin',
  });
  const am = proxy.accountManager;
  am.add_account('openai', 'key-one', `http://127.0.0.1:${mockPort}/v1`, 0);
  am.add_account('openai', 'key-two', `http://127.0.0.1:${mockPort}/v1`, 0);

  const body = JSON.stringify({ model: 'openai/gpt-4o', messages: [{ role: 'user', content: 'hi' }] });

  await proxy.start(0);
  try {
    const s1 = await post(proxy.status().port!, '/v1/chat/completions', body);
    assert.strictEqual(s1.status, 429);
    assert.strictEqual(seen[0].auth, 'Bearer key-one');

    const s2 = await post(proxy.status().port!, '/v1/chat/completions', body);
    assert.strictEqual(s2.status, 200);
    assert.strictEqual(seen[1].auth, 'Bearer key-two');
  } finally {
    await proxy.stop();
    mock.close();
  }
});

test('proxy strips provider prefix from forwarded model', async () => {
  let receivedBody = '';
  const mock = http.createServer((req, res) => {
    let chunks = '';
    req.on('data', (c) => (chunks += c));
    req.on('end', () => {
      receivedBody = chunks;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ id: 'x', choices: [] }));
    });
  });
  const mockPort = await listen(mock);
  proxy.saveConfig({ port: 0, enabled: false, saved_base_urls: { opencode: `http://127.0.0.1:${mockPort}/v1` } });

  const body = JSON.stringify({ model: 'opencode/big-pickle', messages: [{ role: 'user', content: 'hello' }] });

  await proxy.start(0);
  try {
    const s = await post(proxy.status().port!, '/v1/chat/completions', body);
    assert.strictEqual(s.status, 200);
    const parsed = JSON.parse(receivedBody);
    assert.strictEqual(parsed.model, 'big-pickle');
  } finally {
    await proxy.stop();
    mock.close();
  }
});
