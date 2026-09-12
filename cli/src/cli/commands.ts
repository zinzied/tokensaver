import * as config from '../core/config.js';
import * as insights from '../core/insights.js';
import * as models from '../core/models.js';
import * as proxy from '../core/proxy.js';
import * as rtk from '../core/filters/rtk.js';
import * as translate from '../core/translate.js';
import * as prompts from '../core/prompts.js';
import * as todo from '../core/todo.js';
import * as goals from '../core/goals.js';
import * as reminders from '../core/reminders.js';
import { fmt } from '../tui/components.js';
import { BANNER, APP_NAME } from '../banner.js';

const HELP = `${BANNER}${APP_NAME} CLI v${config.TS_VERSION} — reduce token waste and spending when using AI coding models

USAGE
  token-saver [command] [args...]   run a subcommand (non-interactive)
  token-saver [--tui|-i]            launch the interactive TUI (default when run without a command)

COMMANDS
  overview | status                 summary of ledger + proxy savings
  usage                             savings ledger and proxy history
  quota                             provider quota tracker + budget
  routing                           current model, tiers, fallback chains, accounts
  providers                         detected and configured providers
  search <query> [--limit N]        search the compression index
  compress test <text>              run RTK compression test on raw text
  rtk auto <text>                   auto-detect filter and compress text
  proxy status                      show proxy status
  proxy start [--port N]            start the compression proxy
  proxy stop                        stop the proxy
  proxy proxify [--port N]          auto-add all configured providers to the proxy
  proxy enable [--port N]           enable auto-start
  proxy disable                     disable auto-start
  proxy test                        test proxy health + upstream forward
  accounts list                     list proxy accounts
  accounts add --provider P [--key K] [--base-url U] [--priority N]
  models fetch                      fetch the models.dev catalog (updates cache/snapshot)
  models list [--provider P]        list catalog for configured providers
  models choose [--mode paid|free] [--task T] [--max-paid N] [--provider P]
  models recommend [--task T]
  models projection --main M --small S
  models heatmap                    cheapest model per capability
  models policy get                 show the saver policy
  models policy set --mode paid|free [--budget N] [--free-limit N] [--max-paid N]
  models apply --main M [--small S] write main/small model to opencode.jsonc
  settings get                      current config, compaction, backups
  settings save --model M [--small-model S]
  translate detect '<json body>'    detect the request format
  translate convert <from> <to> '<json body>'
  caveman inject [--level lite|full|ultra] '<json body>'
  ponytail inject [--level lite|full|ultra] '<json body>'
  todo add <text>                     add a new todo item
  todo list                          list all todo items
  todo done <id>                     mark a todo as done
  todo cancel <id>                   cancel a todo
  todo remove <id>                   remove a todo
  todo clear                         clear all done todos
  goal add <text>                    add a new goal
  goal list                          list all goals
  goal done <id>                     mark a goal as completed
  goal abandon <id>                  abandon a goal
  goal remove <id>                   remove a goal
  goal clear                         clear all completed goals
  remind add <minutes> <text>        add a reminder in N minutes
  remind list                        list all reminders
  remind due                         show due reminders
  remind remove <id>                 remove a reminder
  remind clear                       clear all fired reminders
`;

function out(line = ''): void {
  console.log(line);
}

function outErr(line: string): void {
  console.error(line);
}

function printTable(head: string[], rows: (string | number)[][]): void {
  if (!rows.length) {
    out('  No data.');
    return;
  }
  const widths = head.map((h, i) => Math.max(h.length, ...rows.map((r) => String(r[i] ?? '').length)));
  const rowStr = (cells: (string | number)[], isHead: boolean): string =>
    cells.map((c, i) => String(c).padEnd(widths[i] + 2)).join('').trimEnd();
  out(rowStr(head, true));
  for (const r of rows) out(rowStr(r, false));
}

function parseFlags(args: string[]): { positionals: string[]; flags: Record<string, string>; bools: Set<string> } {
  const positionals: string[] = [];
  const flags: Record<string, string> = {};
  const bools = new Set<string>();
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith('--')) {
      const eq = a.indexOf('=');
      if (eq !== -1) flags[a.slice(2, eq)] = a.slice(eq + 1);
      else if (i + 1 < args.length && !args[i + 1].startsWith('--')) {
        flags[a.slice(2)] = args[++i];
      } else bools.add(a.slice(2));
    } else positionals.push(a);
  }
  return { positionals, flags, bools };
}

async function cmdOverview(): Promise<number> {
  const u = insights.usageSummary();
  out(BANNER.trimEnd());
  out(`${APP_NAME} v${config.TS_VERSION}`);
  out(`Config: ${config.CONFIG_PATH}`);
  out();
  out(`  Ledger entries    : ${fmt(u.ledger.entries)}`);
  out(`  Ledger tokens saved: ${fmt(u.ledger.saved_tokens)}`);
  out(`  Proxy requests    : ${fmt(u.proxy.requests)}`);
  out(`  Proxy tokens saved: ${fmt(u.proxy.saved_tokens)}`);
  out(`  Proxy bytes saved : ${fmt(u.proxy.saved_bytes)}B`);
  return 0;
}

async function cmdUsage(): Promise<number> {
  const u = insights.usageSummary();
  out(`Ledger entries: ${fmt(u.ledger.entries)}  raw: ${fmt(u.ledger.raw_tokens)}  saved: ${fmt(u.ledger.saved_tokens)}`);
  out(`Proxy requests: ${fmt(u.proxy.requests)}  saved: ${fmt(u.proxy.saved_tokens)} tok / ${fmt(u.proxy.saved_bytes)}B  frost: ${fmt(u.proxy.frost_saved)}`);
  out();
  out('By kind:');
  printTable(['Kind', 'Count', 'Tokens saved'], u.byKind.map((k) => [k.kind, fmt(k.count), fmt(k.saved_tokens)]));
  out();
  out('By model:');
  printTable(['Model', 'Requests', 'Tokens saved', 'Bytes saved'], u.perModel.map((m) => [m.model, fmt(m.requests), fmt(m.saved_tokens), `${fmt(m.saved_bytes)}B`]));
  out();
  out('Recent activity:');
  printTable(['Time', 'Kind', 'Description', 'Saved'], u.recent.map((r) => [r.ts, r.kind, r.description, `${fmt(r.saved)}${r.unit}`]));
  return 0;
}

async function cmdQuota(): Promise<number> {
  const { quota, budget } = insights.quotaSummary();
  const budgetData = budget as Record<string, any> | null;
  if (budgetData) {
    out(`Task: ${budgetData.task || '—'}  budget: ${fmt(budgetData.budget_limit)}  allocated: ${fmt(budgetData.total_allocated)}  remaining: ${fmt(budgetData.remaining)}`);
    out(`Allocation: ${Object.entries(budgetData.allocation || {}).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${fmt(v)}`).join(', ')}`);
    out();
  } else {
    out('No budget.json yet.');
    out();
  }
  const quotaData = quota as Record<string, any>;
  const providers = Object.entries(quotaData?.providers || {});
  out('Providers:');
  printTable(['Provider', 'Total quota', 'Remaining', 'Status', 'Cost', 'Last checked'], providers.map(([pid, p]) => [
    pid,
    fmt((p as any).total_quota),
    fmt((p as any).remaining),
    (p as any).rate_limited_until ? 'rate limited' : (p as any).reset_at ? 'resetting' : '—',
    (p as any).total_cost !== undefined ? `$${Number((p as any).total_cost).toFixed(4)}` : '—',
    (p as any).last_checked ? new Date((p as any).last_checked).toLocaleString() : '—',
  ]));
  out();
  const accounts = Object.entries(quotaData?.accounts || {});
  out('Accounts:');
  printTable(['Account', 'Remaining', 'Status', 'Last used'], accounts.map(([id, a]) => [
    id,
    fmt((a as any).remaining),
    (a as any).rate_limited_until ? 'rate limited' : 'ok',
    (a as any).last_used ? new Date((a as any).last_used).toLocaleString() : '—',
  ]));
  return 0;
}

async function cmdRouting(): Promise<number> {
  const r = insights.routingSummary();
  out(`Current model : ${r.currentModel || '—'}`);
  out(`Upstream      : ${r.upstream ? `${r.upstream.url} (via ${r.upstream.pid})` : 'direct (no proxy)'}`);
  out(`Provider tier : ${r.tier || '—'}`);
  out(`Accounts      : ${r.accounts?.length ?? 0}  strategy: ${r.accountStrategy || 'round-robin'}`);
  out();
  out('Tiered fallback chain:');
  printTable(['#', 'Provider'], r.tieredChain?.map((p, i) => [i + 1, p]) || []);
  out();
  out('Per-model fallback chain:');
  printTable(['#', 'Fallback model'], r.fallbackChain.map((m, i) => [i + 1, m]));
  out();
  out('Provider routing:');
  printTable(['Provider', 'Configured', 'Proxied', 'Base URL'], r.routing.map((x) => [x.provider, x.configured ? 'cfg' : '—', x.proxied ? 'proxy' : '—', x.baseURL || '—']));
  out();
  out('Upstreams:');
  printTable(['Provider', 'Upstream URL'], Object.entries(r.upstreams || {}).map(([pid, url]) => [String(pid), String(url)]));
  out();
  out('Accounts:');
  printTable(['ID', 'Provider', 'Status', 'Priority'], (r.accounts || []).map((a) => [a.id, a.provider, a.status, fmt(a.priority)]));
  return 0;
}

async function cmdProviders(): Promise<number> {
  const list = insights.providersList();
  out(`Detected and configured providers (${list.length} total):`);
  printTable(['Provider', 'Configured', 'Working', 'Env', 'Auth', 'History', 'Proxied', 'Base URL', 'Env vars'],
    list.map((p) => [p.provider, p.configured ? 'yes' : 'no', p.working ? 'yes' : 'no', p.envDetected ? 'yes' : 'no', p.authDetected ? 'yes' : 'no', p.inHistory ? 'yes' : 'no', p.proxied ? 'yes' : 'no', p.baseURL || '—', p.envVars.length ? p.envVars.join(' ') : '—']));
  return 0;
}

async function cmdSearch(args: string[]): Promise<number> {
  const { positionals, flags } = parseFlags(args);
  const q = positionals.join(' ') || '';
  const limit = Number(flags.limit) || 25;
  const results = insights.searchQuery(q, limit);
  if (!results.length) {
    out(`No matches for "${q}".`);
    return 0;
  }
  out(`Search: "${q}" — ${results.length} matches:`);
  printTable(['Source', 'Kind', 'Description', 'Saved', 'Time'], results.map((r) => [
    r.source,
    r.kind || '—',
    r.description || r.path || '—',
    `${fmt(r.saved_tokens)} tok`,
    r.timestamp ? new Date(Number.isFinite(Number(r.timestamp)) ? Number(r.timestamp) * 1000 : r.timestamp).toLocaleString() : '—',
  ]));
  return 0;
}

async function cmdCompressTest(args: string[]): Promise<number> {
  const { positionals } = parseFlags(args);
  const text = positionals.join(' ');
  if (!text) {
    outErr('usage: compress test <text>');
    return 1;
  }
  const r = insights.compressTest(text);
  out(`Detected filter: ${r.detected ?? 'none'}`);
  out(`Characters in   : ${fmt(r.length)}`);
  if (r.tooSmall) {
    out(`Input below minimum size (MIN_COMPRESS_SIZE = ${r.min}); passed through.`);
    return 0;
  }
  out(`Characters out  : ${fmt(r.compressed_length ?? r.length)}`);
  out(`Saved           : ${fmt(r.saved ?? 0)}`);
  out(`Reduction       : ${r.pct ?? 0}%`);
  if (r.compressed) {
    out();
    out('Compressed:');
    out(r.compressed);
  }
  return 0;
}

async function cmdRtkAuto(args: string[]): Promise<number> {
  const { positionals } = parseFlags(args);
  const text = positionals.join(' ');
  if (!text) {
    outErr('usage: rtk auto <text>');
    return 1;
  }
  const fn = rtk.auto_detect_filter(text);
  out(`Detected filter: ${fn ? fn.name : 'none'}`);
  out();
  out(rtk.safe_apply(fn, text));
  return 0;
}

async function cmdProxy(args: string[]): Promise<number> {
  const { positionals, flags, bools } = parseFlags(args);
  const sub = positionals[0] || 'status';
  switch (sub) {
    case 'status': {
      const s = proxy.status();
      out(`Running     : ${s.running ? 'yes' : 'no'}`);
      out(`Port        : ${s.port}`);
      out(`Auto-start  : ${s.enabled ? 'enabled' : 'disabled'}`);
      out(`Requests    : ${fmt(s.requestsServed)}`);
      out(`Hits        : ${fmt(s.compressionHits)}`);
      out(`Bytes saved : ${fmt(s.totalSavedBytes)}B`);
      if (s.lastModel) out(`Last model  : ${s.lastModel}`);
      if (s.proxiedProviders?.length) out(`Proxied     : ${s.proxiedProviders.join(', ')}`);
      const curPid = proxy.modelProvider(config.get_current_model());
      if (curPid) {
        const proxied = (s.proxiedProviders || []).includes(curPid);
        out(`Current     : ${curPid} ${proxied ? '(proxied)' : '(NOT proxied — may bypass the proxy)'}`);
      }
      return 0;
    }
    case 'start': {
      const s = await proxy.start(flags.port ? Number(flags.port) : undefined);
      out(`Proxy listening on http://127.0.0.1:${s.port}`);
      return 0;
    }
    case 'stop': {
      const s = await proxy.stop();
      out(`Proxy stopped. running=${s.running}`);
      return 0;
    }
    case 'proxify': {
      const r = proxy.ensureProxiedProviders(flags.port ? Number(flags.port) : undefined, true);
      if (r.added.length) out(`Added to proxy: ${r.added.join(', ')}`);
      if (r.already.length) out(`Already proxied: ${r.already.join(', ')}`);
      if (r.skipped.length) out(`Skipped (no known upstream): ${r.skipped.join(', ')}`);
      if (r.rewritten.length) out(`Routed through proxy (opencode.jsonc): ${r.rewritten.join(', ')}`);
      if (!r.added.length && !r.rewritten.length) out('All detected providers are already proxied.');
      if (r.rewritten.length) out('Restart opencode if it is running for the new routing to take effect.');
      return 0;
    }
    case 'enable': {
      proxy.enable(true, flags.port ? Number(flags.port) : undefined);
      out('Auto-start enabled.');
      return 0;
    }
    case 'disable': {
      proxy.enable(false);
      out('Auto-start disabled.');
      return 0;
    }
    case 'test': {
      const t = await proxy.testConnection();
      if (t.running === false) {
        out('Proxy is not running.');
        return 1;
      }
      out(`Proxy health: ${t.health ? (t.health.ok ? `HTTP ${t.health.code} OK` : `HTTP ${t.health.code ?? 'no response'}`) : 'no response'}`);
      if (t.forward) {
        out(`Upstream forward: HTTP ${t.forward.code}${t.forward.upstream ? ` (${t.forward.upstream})` : ''}`);
        if (t.forward.code === 401) out('  proxy reached the upstream; add your API key to the client');
        if (t.forward.error) out(`  ${t.forward.error}`);
      } else {
        out('Upstream forward: no response');
      }
      return 0;
    }
    default:
      outErr(`unknown proxy subcommand: ${sub}`);
      return 1;
  }
}

async function cmdAccounts(args: string[]): Promise<number> {
  const { positionals, flags } = parseFlags(args);
  const sub = positionals[0] || 'list';
  switch (sub) {
    case 'list': {
      const accounts = proxy.accountManager.get_summary();
      printTable(['ID', 'Provider', 'Status', 'Priority'], accounts.map((a) => [a.id, a.provider, a.status, fmt(a.priority)]));
      return 0;
    }
    case 'add': {
      if (!flags.provider) {
        outErr('usage: accounts add --provider P [--key K] [--base-url U] [--priority N]');
        return 1;
      }
      const id = proxy.accountManager.add_account(flags.provider, flags.key || null, flags['base-url'] || null, Number(flags.priority) || 0);
      out(`Added ${id}`);
      return 0;
    }
    default:
      outErr(`unknown accounts subcommand: ${sub}`);
      return 1;
  }
}

async function cmdModels(args: string[]): Promise<number> {
  const { positionals, flags } = parseFlags(args);
  const sub = positionals[0] || 'list';
  switch (sub) {
    case 'fetch': {
      out('Fetching models.dev catalog…');
      const r = await models.fetchCatalog();
      if (r.catalog) out(`Catalog ${r.source === 'network' ? 'updated' : 'loaded'}${r.newModels?.length ? ` — ${r.newModels.length} new models` : ''}`);
      else outErr(r.error || 'Failed to fetch catalog.');
      return r.catalog ? 0 : 1;
    }
    case 'list': {
      const catalog = models.get_user_models_sync();
      const filter = (flags.provider || '').toLowerCase();
      const providers = Object.entries(catalog);
      if (!providers.length) {
        out('No catalog cache found. Run "models fetch" first.');
        return 0;
      }
      for (const [key, pd] of providers) {
        if (filter && !pd.id.includes(filter) && !key.toLowerCase().includes(filter)) continue;
        out(`${pd.name} (${pd.id})${pd.configured ? ' — configured' : ''}`);
        printTable(['Model', 'Context', 'Tools', 'Reasoning', 'In/Out $/M'],
          (pd.models || []).map((m) => [m.name, fmt(m.context), m.tool_call ? 'yes' : '—', m.reasoning ? 'yes' : '—', m.is_free ? 'FREE' : `$${m.input_price}/${m.output_price}`]));
        out();
      }
      return 0;
    }
    case 'choose': {
      const catalog = models.get_user_models_sync();
      const mode = flags.mode === 'free' ? 'free' : 'paid';
      const task = flags.task || 'coding';
      const maxPaid = Number(flags['max-paid']) || 5;
      const r = models.choose_saver_models(catalog, mode, task, maxPaid, flags.provider || null);
      if (r.error) {
        outErr(r.error);
        return 1;
      }
      out(`Main  : ${r.main.name}  (${r.main.id})  ${r.main.is_free ? 'FREE' : `$${r.main.input_price}/${r.main.output_price} per M`}`);
      out(`Small : ${r.small.name}  (${r.small.id})  ${r.small.is_free ? 'FREE' : `$${r.small.input_price}/${r.small.output_price} per M`}`);
      out(`Fallbacks: ${r.fallbacks.join(', ') || '—'}`);
      out(`Pool: ${r.configured_count} cfg · ${r.free_count} free · ${r.paid_allowed_count} allowed`);
      return 0;
    }
    case 'recommend': {
      const catalog = models.get_user_models_sync();
      const task = flags.task || 'coding';
      const r = models.recommend_models(catalog, task);
      if (!r.configured) {
        out('No configured providers found. Add API keys first.');
        return 0;
      }
      printTable(['Model', 'Provider', 'Price', 'Recommended for'],
        r.items.map((it: any) => [it.model.name, it.model.provider, it.model.is_free ? 'FREE' : `$${it.model.input_price}/${it.model.output_price} per M`, `${it.desc} [${it.tag}]`]));
      return 0;
    }
    case 'projection': {
      if (!flags.main || !flags.small) {
        outErr('usage: models projection --main M --small S');
        return 1;
      }
      const catalog = models.get_user_models_sync();
      const r = models.cost_projection(catalog, flags.main, flags.small);
      printTable(['Scenario', 'Main model', 'Small model', 'Savings'],
        r.rows.map((row: any) => [row.label, row.main !== undefined ? `$${row.main.toFixed(2)}` : 'N/A', row.small !== undefined ? `$${row.small.toFixed(2)}` : 'N/A', row.saved_pct ? `~${row.saved_pct}%` : '—']));
      out('+ compaction saves ~30-50% more, compression saves 60-90% on reads/shell.');
      return 0;
    }
    case 'heatmap': {
      const catalog = models.get_user_models_sync();
      const heat = models.heatmap(catalog);
      if (!heat.length) {
        out('No configured providers. Add API keys first.');
        return 0;
      }
      printTable(['Capability', 'Model', 'Price', 'Provider'],
        heat.map((h: any) => [h.label, h.model.name, h.model.is_free ? 'FREE' : `$${h.model.input_price}/${h.model.output_price} per M`, h.model.provider]));
      return 0;
    }
    case 'policy': {
      if (positionals[1] === 'get') {
        const p = models.read_saver_policy();
        out(`mode=${p.mode} · budget $${p.daily_budget_usd}/day · free limit ${fmt(p.free_daily_token_limit)}/day · max $${p.max_paid_cost_per_million}/M`);
        return 0;
      }
      if (positionals[1] === 'set') {
        const cur = models.read_saver_policy();
        const next: any = { ...cur };
        if (flags.mode === 'paid' || flags.mode === 'free') next.mode = flags.mode;
        if (flags.budget !== undefined) next.daily_budget_usd = Number(flags.budget);
        if (flags['free-limit'] !== undefined) next.free_daily_token_limit = Number(flags['free-limit']);
        if (flags['max-paid'] !== undefined) next.max_paid_cost_per_million = Number(flags['max-paid']);
        models.write_saver_policy(next);
        out(`Policy saved: mode=${next.mode} · budget $${next.daily_budget_usd}/day · free limit ${fmt(next.free_daily_token_limit)}/day · max $${next.max_paid_cost_per_million}/M`);
        return 0;
      }
      outErr('usage: models policy get|set');
      return 1;
    }
    case 'apply': {
      if (!flags.main) {
        outErr('usage: models apply --main M [--small S]');
        return 1;
      }
      config.write_config(flags.main, flags.small || '');
      out(`Applied main=${flags.main} small=${flags.small || ''}`);
      return 0;
    }
    default:
      outErr(`unknown models subcommand: ${sub}`);
      return 1;
  }
}

async function cmdSettings(args: string[]): Promise<number> {
  const { positionals, flags } = parseFlags(args);
  const sub = positionals[0] || 'get';
  if (sub === 'get') {
    const s = insights.settingsGet();
    out(`Config path    : ${s.path}`);
    out(`Model          : ${s.model || '—'}`);
    out(`Small model    : ${s.small_model || '—'}`);
    out(`Current        : ${s.current || '—'}`);
    out(`Providers      : ${fmt(s.providerCount)} (${s.providers.join(', ') || '—'})`);
    if (s.compaction) out(`Compaction     : ${Object.entries(s.compaction).map(([k, v]) => `${k}=${String(v)}`).join('  ')}`);
    if (s.backups.length) {
      out();
      out('Backups:');
      printTable(['Backup', 'Path'], s.backups.map(([label, p]) => [label, p]));
    }
    return 0;
  }
  if (sub === 'save') {
    const s = insights.settingsSave({ model: flags.model, small_model: flags['small-model'] });
    out(`Saved. model=${s.model} small_model=${s.small_model}`);
    return 0;
  }
  outErr(`unknown settings subcommand: ${sub}`);
  return 1;
}

async function cmdTranslate(args: string[]): Promise<number> {
  const { positionals } = parseFlags(args);
  const sub = positionals[0];
  if (sub === 'detect') {
    const body = JSON.parse(positionals[1] || '{}');
    out(`format: ${translate.detect_format(body)}`);
    return 0;
  }
  if (sub === 'convert') {
    const [, from, to, raw] = positionals;
    if (!from || !to || raw === undefined) {
      outErr('usage: translate convert <from> <to> "<json body>"');
      return 1;
    }
    const body = JSON.parse(raw);
    const result = translate.translate_request(from, to, body);
    out(JSON.stringify(result, null, 2));
    return 0;
  }
  outErr('usage: translate detect|convert');
  return 1;
}

async function cmdInject(args: string[], kind: 'caveman' | 'ponytail'): Promise<number> {
  const { positionals, flags } = parseFlags(args);
  const level = flags.level || 'lite';
  const raw = positionals.join(' ');
  if (!raw) {
    outErr(`usage: ${kind} inject [--level lite|full|ultra] "<json body>"`);
    return 1;
  }
  const body = JSON.parse(raw);
  if (kind === 'caveman') prompts.inject_caveman(body, level);
  else prompts.inject_ponytail(body, level);
  out(JSON.stringify(body, null, 2));
  return 0;
}

function cmdTodo(args: string[]): number {
  const { positionals } = parseFlags(args);
  const sub = positionals[0];
  const rest = positionals.slice(1);

  switch (sub) {
    case 'add': {
      const text = rest.join(' ');
      if (!text) { outErr('usage: todo add <text>'); return 1; }
      const item = todo.addTodo(text);
      out(`+ ${item.id}  ${item.text}`);
      return 0;
    }
    case 'list': {
      const store = todo.loadTodo();
      if (!store.items.length) { out('No todos.'); return 0; }
      printTable(['ID', 'Status', 'Task', 'Created'], store.items.map((i) => [
        i.id,
        i.status,
        i.text,
        new Date(i.created).toLocaleString(),
      ]));
      return 0;
    }
    case 'done': {
      const id = rest[0];
      if (!id) { outErr('usage: todo done <id>'); return 1; }
      const item = todo.completeTodo(id);
      if (!item) { outErr(`Todo ${id} not found.`); return 1; }
      out(`\u2713 ${item.id}  ${item.text}`);
      return 0;
    }
    case 'cancel': {
      const id = rest[0];
      if (!id) { outErr('usage: todo cancel <id>'); return 1; }
      const item = todo.cancelTodo(id);
      if (!item) { outErr(`Todo ${id} not found.`); return 1; }
      out(`\u2717 ${item.id}  ${item.text}`);
      return 0;
    }
    case 'remove': {
      const id = rest[0];
      if (!id) { outErr('usage: todo remove <id>'); return 1; }
      const ok = todo.removeTodo(id);
      if (!ok) { outErr(`Todo ${id} not found.`); return 1; }
      out(`Removed ${id}.`);
      return 0;
    }
    case 'clear': {
      const n = todo.clearDoneTodos();
      out(`Cleared ${n} done item(s).`);
      return 0;
    }
    default:
      outErr('usage: todo add|list|done|cancel|remove|clear');
      return 1;
  }
}

function cmdGoals(args: string[]): number {
  const { positionals } = parseFlags(args);
  const sub = positionals[0];
  const rest = positionals.slice(1);

  switch (sub) {
    case 'add': {
      const text = rest.join(' ');
      if (!text) { outErr('usage: goal add <text>'); return 1; }
      const g = goals.addGoal(text);
      out(`+ ${g.id}  ${g.text}`);
      return 0;
    }
    case 'list': {
      const store = goals.loadGoals();
      if (!store.goals.length) { out('No goals.'); return 0; }
      printTable(['ID', 'Status', 'Goal', 'Created'], store.goals.map((g) => [
        g.id,
        g.status,
        g.text,
        new Date(g.created).toLocaleString(),
      ]));
      return 0;
    }
    case 'done': {
      const id = rest[0];
      if (!id) { outErr('usage: goal done <id>'); return 1; }
      const g = goals.completeGoal(id);
      if (!g) { outErr(`Goal ${id} not found.`); return 1; }
      out(`\u2713 ${g.id}  ${g.text}`);
      return 0;
    }
    case 'abandon': {
      const id = rest[0];
      if (!id) { outErr('usage: goal abandon <id>'); return 1; }
      const g = goals.abandonGoal(id);
      if (!g) { outErr(`Goal ${id} not found.`); return 1; }
      out(`\u2717 ${g.id}  ${g.text}`);
      return 0;
    }
    case 'remove': {
      const id = rest[0];
      if (!id) { outErr('usage: goal remove <id>'); return 1; }
      const ok = goals.removeGoal(id);
      if (!ok) { outErr(`Goal ${id} not found.`); return 1; }
      out(`Removed ${id}.`);
      return 0;
    }
    case 'clear': {
      const n = goals.clearCompletedGoals();
      out(`Cleared ${n} completed goal(s).`);
      return 0;
    }
    default:
      outErr('usage: goal add|list|done|abandon|remove|clear');
      return 1;
  }
}

function cmdRemind(args: string[]): number {
  const { positionals } = parseFlags(args);
  const sub = positionals[0];
  const rest = positionals.slice(1);

  switch (sub) {
    case 'add': {
      const mins = parseInt(rest[0], 10);
      const text = rest.slice(1).join(' ');
      if (!mins || mins <= 0 || !text) { outErr('usage: remind add <minutes> <text>'); return 1; }
      const dueAt = new Date(Date.now() + mins * 60 * 1000);
      const r = reminders.addReminder(text, dueAt);
      out(`+ ${r.id}  "${r.text}" due ${dueAt.toLocaleString()}`);
      return 0;
    }
    case 'list': {
      const store = reminders.loadReminders();
      if (!store.reminders.length) { out('No reminders.'); return 0; }
      printTable(['ID', 'Text', 'Due', 'Fired'], store.reminders.map((r) => [
        r.id,
        r.text,
        new Date(r.dueAt).toLocaleString(),
        r.fired ? 'yes' : 'no',
      ]));
      return 0;
    }
    case 'due': {
      const due = reminders.getDueReminders();
      if (!due.length) { out('No due reminders.'); return 0; }
      printTable(['ID', 'Text', 'Due'], due.map((r) => [
        r.id,
        r.text,
        new Date(r.dueAt).toLocaleString(),
      ]));
      return 0;
    }
    case 'remove': {
      const id = rest[0];
      if (!id) { outErr('usage: remind remove <id>'); return 1; }
      const ok = reminders.removeReminder(id);
      if (!ok) { outErr(`Reminder ${id} not found.`); return 1; }
      out(`Removed ${id}.`);
      return 0;
    }
    case 'clear': {
      const n = reminders.clearFiredReminders();
      out(`Cleared ${n} fired reminder(s).`);
      return 0;
    }
    default:
      outErr('usage: remind add|list|due|remove|clear');
      return 1;
  }
}

export async function runCommand(argv: string[]): Promise<number> {
  if (!argv.length || argv[0] === 'help' || argv[0] === '--help' || argv[0] === '-h') {
    out(HELP);
    return 0;
  }
  const [cmd, ...rest] = argv;
  switch (cmd) {
    case 'overview':
    case 'status':
      return cmdOverview();
    case 'usage':
      return cmdUsage();
    case 'quota':
      return cmdQuota();
    case 'routing':
      return cmdRouting();
    case 'providers':
      return cmdProviders();
    case 'search':
      return cmdSearch(rest);
    case 'compress': {
      const { positionals } = parseFlags(rest);
      if (positionals[0] === 'test') return cmdCompressTest(positionals.slice(1));
      outErr('usage: compress test <text>');
      return 1;
    }
    case 'rtk': {
      const { positionals } = parseFlags(rest);
      if (positionals[0] === 'test') return cmdCompressTest(positionals.slice(1));
      return cmdRtkAuto(positionals[0] === 'auto' ? positionals.slice(1) : positionals);
    }
    case 'proxy':
      return cmdProxy(rest);
    case 'accounts':
      return cmdAccounts(rest);
    case 'models':
      return cmdModels(rest);
    case 'settings':
      return cmdSettings(rest);
    case 'translate':
      return cmdTranslate(rest);
    case 'caveman':
      return cmdInject(rest, 'caveman');
    case 'ponytail':
      return cmdInject(rest, 'ponytail');
    case 'todo':
      return cmdTodo(rest);
    case 'goal':
      return cmdGoals(rest);
    case 'remind':
      return cmdRemind(rest);
    default:
      outErr(`Unknown command: ${cmd}`);
      outErr(`Run "token-saver help" for usage.`);
      return 1;
  }
}
