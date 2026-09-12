import React, { useCallback, useEffect, useState } from 'react';
import { Box, Text } from 'ink';
import { Page, Section, Row, Stat, Table, Hint, ErrorLine, Form, fmt, price, T } from '../components.js';
import { useScreenInput } from '../input.js';
import * as models from '../../core/models.js';
import { write_config } from '../../core/config.js';
import type { ChosenSaverModels, ProviderCatalog, SaverPolicy } from '../../core/types.js';

const TASKS = [
  { id: 'coding', label: 'Coding' },
  { id: 'review', label: 'Code review' },
  { id: 'planning', label: 'Planning / architecture' },
];

export function ModelsPage() {
  const [list, setList] = useState<ProviderCatalog | null>(null);
  const [policy, setPolicy] = useState<SaverPolicy | null>(null);
  const [newModels, setNewModels] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [taskIdx, setTaskIdx] = useState(0);
  const [recs, setRecs] = useState<any>(null);
  const [chosen, setChosen] = useState<ChosenSaverModels | null>(null);
  const [projection, setProjection] = useState<any>(null);
  const [heat, setHeat] = useState<any[] | null>(null);
  const [form, setForm] = useState<'saver' | 'policy' | null>(null);
  const [saverMode, setSaverMode] = useState('paid');
  const [maxPaid, setMaxPaid] = useState('5');
  const [providerFilter, setProviderFilter] = useState('');
  const [policyDraft, setPolicyDraft] = useState<Record<string, any>>({});
  const [catalogAll, setCatalogAll] = useState(false);

  const loadList = useCallback(() => {
    setBusy(true);
    setError('');
    try {
      setList(models.get_user_models_sync());
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    loadList();
    try {
      setPolicy(models.read_saver_policy());
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }, [loadList]);

  function refresh() {
    setBusy(true);
    setError('');
    Promise.resolve()
      .then(() => models.fetchCatalog())
      .then((r) => {
        if (r.newModels && r.newModels.length) setNewModels(r.newModels);
        if (r.error) setError(`Catalog fetch failed (using cache): ${r.error}`);
      })
      .catch((e) => setError(String((e as Error).message || e)))
      .finally(() => {
        loadList();
        setBusy(false);
      });
  }

  function runRecommend() {
    setBusy(true);
    setError('');
    try {
      setRecs(models.recommend_models(list as ProviderCatalog, TASKS[taskIdx].id));
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  }

  function pickSaver() {
    setBusy(true);
    setError('');
    setChosen(null);
    setProjection(null);
    try {
      const r = models.choose_saver_models(
        list as ProviderCatalog,
        saverMode as 'paid' | 'free',
        TASKS[taskIdx].id,
        Number(maxPaid),
        providerFilter.trim() || null
      );
      if (r.error) {
        setError(r.error);
        return;
      }
      setChosen(r);
      setProjection(
        models.cost_projection(list as ProviderCatalog, r.main && r.main.id, r.small && r.small.id)
      );
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  }

  function applyChosen() {
    if (!chosen || !chosen.main) return;
    setBusy(true);
    setError('');
    try {
      write_config(chosen.main.id, chosen.small ? chosen.small.id : '');
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
      loadList();
    }
  }

  function savePolicy() {
    setBusy(true);
    setError('');
    try {
      models.write_saver_policy(policyDraft as SaverPolicy);
      setPolicy(models.read_saver_policy());
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  }

  useScreenInput((k) => {
    if (k.q || k.up || k.down || k.esc) return false;
    if (form) return false;
    switch (k.input) {
      case 'r':
        loadList();
        return true;
      case 'f':
        refresh();
        return true;
      case 't':
        setTaskIdx((i) => (i + 1) % TASKS.length);
        return true;
      case 'c':
        runRecommend();
        return true;
      case 'p':
        setForm('saver');
        return true;
      case 'a':
        applyChosen();
        return true;
      case 'x':
        setCatalogAll((v) => !v);
        return true;
      case 'g':
        setBusy(true);
        setError('');
        try {
          setHeat(models.heatmap(list as ProviderCatalog));
        } catch (e) {
          setError(String((e as Error).message || e));
        } finally {
          setBusy(false);
        }
        return true;
      case 'o':
        if (chosen && chosen.main) {
          setBusy(true);
          try {
            setProjection(
              models.cost_projection(list as ProviderCatalog, chosen.main.id, chosen.small ? chosen.small.id : '')
            );
          } catch (e) {
            setError(String((e as Error).message || e));
          } finally {
            setBusy(false);
          }
        }
        return true;
      case 'v':
        setPolicyDraft({ ...(policy || {}) });
        setForm('policy');
        return true;
      default:
        return false;
    }
  });

  const providers = Object.entries(list || {});
  const modelCount = providers.reduce((n, [, pd]) => n + (pd.models ? pd.models.length : 0), 0);

  return (
    <Page
      title="Models"
      sub={
        list
          ? `Model catalog across your configured providers — ${providers.length} providers, ${modelCount} models.`
          : undefined
      }
    >
      {error && <ErrorLine>{error}</ErrorLine>}
      {busy && <Hint>Working…</Hint>}
      {!list && !error && <Hint>Loading…</Hint>}
      <Hint>
        r: refresh list · f: fetch catalog · t: task ({TASKS[taskIdx].label}) · c: recommend · p: pick saver · a: apply
        · g: heatmap · o: projection · v: edit policy
      </Hint>
      {newModels.length > 0 && (
        <Hint>New models since last snapshot: {newModels.length} (press f to refresh catalog)</Hint>
      )}
      {form === 'saver' && (
        <Form
          title="Pick saver models"
          fields={[
            { label: 'Mode (paid/free)', get: () => saverMode, set: setSaverMode },
            { label: 'Max $/M paid', get: () => maxPaid, set: setMaxPaid },
            { label: 'Provider filter (optional)', get: () => providerFilter, set: setProviderFilter },
          ]}
          onDone={() => {
            setForm(null);
            pickSaver();
          }}
          onCancel={() => setForm(null)}
        />
      )}
      {form === 'policy' && (
        <Form
          title="Edit saver policy"
          fields={[
            { label: 'Mode (paid/free)', get: () => String(policyDraft.mode ?? 'paid'), set: (v) => setPolicyDraft((d) => ({ ...d, mode: v })) },
            { label: 'Daily budget $', get: () => String(policyDraft.daily_budget_usd ?? 1), set: (v) => setPolicyDraft((d) => ({ ...d, daily_budget_usd: Number(v) })) },
            { label: 'Free token limit / day', get: () => String(policyDraft.free_daily_token_limit ?? 100000), set: (v) => setPolicyDraft((d) => ({ ...d, free_daily_token_limit: Number(v) })) },
            { label: 'Max $/M', get: () => String(policyDraft.max_paid_cost_per_million ?? 5), set: (v) => setPolicyDraft((d) => ({ ...d, max_paid_cost_per_million: Number(v) })) },
          ]}
          onDone={() => {
            setForm(null);
            savePolicy();
          }}
          onCancel={() => setForm(null)}
        />
      )}
      {policy && (
        <Hint>
          Policy: mode={policy.mode} · budget ${policy.daily_budget_usd}/day · free limit{' '}
          {fmt(policy.free_daily_token_limit)}/day · max ${policy.max_paid_cost_per_million}/M
        </Hint>
      )}
      {recs && !recs.configured && <Hint>No configured providers found. Add API keys first.</Hint>}
      {recs && recs.configured && (
        <Section title="Recommendations">
          <Table
            head={['Model', 'Provider', 'Price', 'Recommended for']}
            rows={recs.items.map((it: any) => [T(it.model.name), T(it.model.provider), T(price(it.model)), T(`${it.desc} [${it.tag}]`)])}
          />
        </Section>
      )}
      {chosen && !chosen.error && (
        <Section title="Auto saver">
          <Row>
            <Stat label="Main model" value={chosen.main.name} sub={`${chosen.main.id}  ${price(chosen.main)}`} />
            <Stat label="Small model" value={chosen.small.name} sub={`${chosen.small.id}  ${price(chosen.small)}`} />
            <Stat label="Fallbacks" value={chosen.fallbacks.join(', ') || '—'} />
            <Stat
              label="Pool"
              value={`${chosen.configured_count} cfg · ${chosen.free_count} free · ${chosen.paid_allowed_count} allowed`}
            />
          </Row>
          <Hint>Press a to apply to opencode config, o to recompute projection.</Hint>
        </Section>
      )}
      {projection && (
        <Section title="Cost projection">
          <Table
            head={['Scenario', 'Main model', 'Small model', 'Savings']}
            rows={projection.rows.map((r: any) => [
              T(r.label),
              T(r.main !== undefined ? `$${r.main.toFixed(2)}` : 'N/A'),
              T(r.small !== undefined ? `$${r.small.toFixed(2)}` : 'N/A'),
              T(r.saved_pct ? `~${r.saved_pct}%` : '—'),
            ])}
          />
          <Hint>+ compaction saves ~30-50% more, compression saves 60-90% on reads/shell.</Hint>
        </Section>
      )}
      {heat && heat.length > 0 && (
        <Section title="Cheapest per capability">
          <Table
            head={['Capability', 'Model', 'Price', 'Provider']}
            rows={heat.map((h: any) => [T(h.label), T(h.model.name), T(price(h.model)), T(h.model.provider)])}
          />
        </Section>
      )}
      {list && (
        <Section title="Catalog preview">
          <Hint>
            {catalogAll
              ? 'Showing all providers. Press x to show only configured ones.'
              : 'Showing configured providers only. Press x to show all.'}
          </Hint>
          {providers
            .filter(([, pd]) => catalogAll || pd.configured)
            .map(([key, pd]) => (
              <Box2 key={key} pd={pd} />
            ))}
        </Section>
      )}
    </Page>
  );
}

function Box2({ pd }: { pd: any }) {
  const rows = (pd.models || []).map((m: any) => [
    T(m.name),
    T(fmt(m.context)),
    T(m.tool_call ? 'yes' : '—'),
    T(m.reasoning ? 'yes' : '—'),
    T(price(m)),
  ]);
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold color="magenta">
        {pd.name} ({pd.id})
        {pd.configured ? ' — configured' : ''}
      </Text>
      <Table head={['Model', 'Context', 'Tools', 'Reasoning', 'In/Out $/M']} rows={rows} />
    </Box>
  );
}
