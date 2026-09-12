import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { test } from 'node:test';
import assert from 'node:assert';

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-models-'));
process.env.TOKENSAVER_HOME = TMP;
process.env.OPENAI_API_KEY = 'sk-test';
process.env.DEEPSEEK_API_KEY = 'ds-test';
process.env.GLM_API_KEY = 'glm-test';

const config = await import('../src/core/config.js');
const models = await import('../src/core/models.js');

const CATALOG: Record<string, any> = {
  openai: {
    name: 'OpenAI',
    models: {
      'gpt-4o': { name: 'GPT-4o', cost: { input: 2.5, output: 10 }, limit: { context: 128000 }, tool_call: true, reasoning: false },
      'gpt-4o-mini': { name: 'GPT-4o mini', cost: { input: 0.15, output: 0.6 }, limit: { context: 128000 }, tool_call: true },
      'gpt-4': { name: 'GPT-4', cost: { input: 30, output: 60 }, limit: { context: 8192 }, tool_call: true },
    },
  },
  deepseek: {
    name: 'DeepSeek',
    models: {
      'deepseek-chat': { name: 'DeepSeek Chat', cost: { input: 0.27, output: 1.1 }, limit: { context: 64000 }, tool_call: true },
    },
  },
  glm: {
    name: 'GLM',
    models: {
      'glm-4-flash': { name: 'GLM-4 Flash', cost: { input: 0, output: 0 }, limit: { context: 128000 }, tool_call: true },
    },
  },
};

function seedCatalog() {
  fs.mkdirSync(path.dirname(config.CACHE_PATH), { recursive: true });
  fs.writeFileSync(config.CACHE_PATH, JSON.stringify(CATALOG), 'utf-8');
}

test('build_snapshot / save_snapshot / load_snapshot round-trip', () => {
  const snap = models.buildSnapshot(CATALOG);
  assert.deepStrictEqual(snap.openai, ['gpt-4', 'gpt-4o', 'gpt-4o-mini']);
  assert.deepStrictEqual(snap.deepseek, ['deepseek-chat']);
  models.saveSnapshot(CATALOG);
  assert.deepStrictEqual(models.loadSnapshot(), snap);
});

test('diffNewModels reports only newly added models', () => {
  const oldSnap = { openai: ['gpt-4o'], deepseek: ['deepseek-chat'], glm: ['glm-4-flash'] };
  const added = models.diffNewModels(oldSnap, CATALOG);
  assert.strictEqual(added.length, 2);
  assert.ok(added.some((m: any) => m.model_name === 'GPT-4'));
  assert.ok(added.some((m: any) => m.model_name === 'GPT-4o mini'));
  const m = added.find((x: any) => x.model_name === 'GPT-4');
  assert.strictEqual(m!.is_free, false);
  assert.strictEqual(m!.context, 8192);
});

test('get_user_models_sync marks env-configured providers and sorts by price', () => {
  seedCatalog();
  const um = models.get_user_models_sync();
  assert.ok(um['openai (OpenAI)'].configured);
  assert.ok(um['glm (GLM)'].configured);
  const prices = um['openai (OpenAI)'].models.map((m: any) => m.input_price + m.output_price);
  assert.deepStrictEqual(prices, [0.75, 12.5, 90]);
  const mini = um['openai (OpenAI)'].models.find((m: any) => m.id === 'openai/gpt-4o-mini');
  assert.strictEqual(mini!.cache_price, null);
  assert.strictEqual(mini!.tool_call, true);
});

test('choose_saver_models picks cheapest tool-capable main with fallbacks', () => {
  const um = models.get_user_models_sync();
  const r = models.choose_saver_models(um, 'paid', 'coding', 5.0);
  assert.strictEqual(r.error, undefined);
  assert.strictEqual(r.main.id, 'glm/glm-4-flash');
  assert.strictEqual(r.small.id, 'glm/glm-4-flash');
  assert.deepStrictEqual(r.fallbacks, ['openai/gpt-4o-mini', 'deepseek/deepseek-chat']);
  assert.strictEqual(r.configured_count, 5);
  assert.strictEqual(r.free_count, 1);
  assert.strictEqual(r.paid_allowed_count, 2);
});

test('choose_saver_models filters by provider and errors cleanly', () => {
  const um = models.get_user_models_sync();
  const r = models.choose_saver_models(um, 'paid', 'coding', 5.0, 'openai');
  assert.strictEqual(r.main.id, 'openai/gpt-4o-mini');
  const err = models.choose_saver_models(um, 'paid', 'coding', 5.0, 'nobody');
  assert.match(err.error!, /No usable models found for provider 'nobody'/);
});

test('recommend_models returns strong + balanced per task', () => {
  const um = models.get_user_models_sync();
  const r = models.recommend_models(um, 'coding');
  assert.strictEqual(r.configured, true);
  assert.strictEqual(r.items[0].tag, 'strong');
  assert.strictEqual(r.items[0].model.id, 'openai/gpt-4');
  assert.strictEqual(r.items[1].tag, 'balanced');
  assert.strictEqual(r.items[1].model.id, 'glm/glm-4-flash');
});

test('cost_projection computes scenario costs in dollars', () => {
  const um = models.get_user_models_sync();
  const p = models.cost_projection(um, 'deepseek/deepseek-chat', 'glm/glm-4-flash');
  assert.ok(p.main);
  assert.strictEqual(p.rows.length, 3);
  const light = p.rows[0];
  assert.ok(Math.abs(light.main - 0.049) < 0.0001);
  assert.strictEqual(light.small, 0);
});

test('heatmap picks best model per capability', () => {
  const um = models.get_user_models_sync();
  const h = models.heatmap(um);
  const labels = h.map((x: any) => x.label);
  assert.ok(labels.includes('Cheapest overall'));
  assert.strictEqual(h.find((x: any) => x.label === 'Cheapest overall')!.model.id, 'glm/glm-4-flash');
  assert.strictEqual(h.find((x: any) => x.label === 'Cheapest w/ tools')!.model.id, 'glm/glm-4-flash');
  assert.ok(!labels.includes('Cheapest reasoning'));
});

test('saver policy reads defaults and persists', () => {
  const def = models.read_saver_policy();
  assert.strictEqual(def.mode, 'paid');
  assert.strictEqual(def.max_paid_cost_per_million, 5.0);
  models.write_saver_policy({ ...def, mode: 'free', daily_budget_usd: 2.5 });
  const saved = models.read_saver_policy();
  assert.strictEqual(saved.mode, 'free');
  assert.strictEqual(saved.daily_budget_usd, 2.5);
});

test('fetchCatalog serves a fresh cache without network', async () => {
  seedCatalog();
  const r = await models.fetchCatalog();
  assert.strictEqual(r.source, 'cache');
  assert.deepStrictEqual(r.newModels, []);
  assert.ok(r.catalog!.openai);
});

test('normalize_provider_filter collapses wildcards', () => {
  assert.strictEqual(models.normalize_provider_filter('any'), null);
  assert.strictEqual(models.normalize_provider_filter('*'), null);
  assert.strictEqual(models.normalize_provider_filter(' OpenAI '), 'openai');
  assert.strictEqual(models.normalize_provider_filter(null), null);
});
