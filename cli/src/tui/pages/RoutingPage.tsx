import React, { useState } from 'react';
import { Page, Section, Row, Stat, Table, Hint, ErrorLine, SuccessLine, Form, fmt, T } from '../components.js';
import { useScreenInput } from '../input.js';
import { useData } from '../useData.js';
import { routingSummary } from '../../core/insights.js';
import { accountManager } from '../../core/proxy.js';

const TIER_CATALOG: Record<string, Record<string, { cost?: string; format?: string }>> = {
  subscription: {
    'claude-code': { cost: '$20-200/mo', format: 'claude' },
    codex: { cost: '$20-200/mo', format: 'openai' },
    'github-copilot': { cost: '$10-19/mo', format: 'openai' },
    cursor: { cost: '$20/mo', format: 'openai' },
    'gemini-cli': { cost: '$20/mo', format: 'gemini' },
  },
  cheap: {
    glm: { cost: '$0.6/1M', format: 'openai' },
    minimax: { cost: '$0.2/1M', format: 'openai' },
    kimi: { cost: '$9/mo flat', format: 'openai' },
  },
  free: {
    kiro: { cost: 'Free', format: 'openai' },
    'opencode-free': { cost: 'Free', format: 'openai' },
    vertex: { cost: 'Free credits', format: 'vertex' },
    iflow: { cost: 'Free', format: 'openai' },
    qwen: { cost: 'Free', format: 'openai' },
  },
};

function getProviderMeta(providerId: string): { tier: string; cost: string; format: string } {
  for (const tier of ['subscription', 'cheap', 'free'] as const) {
    const catalog = TIER_CATALOG[tier];
    if (catalog && catalog[providerId]) {
      return { tier, cost: catalog[providerId].cost || '—', format: catalog[providerId].format || '' };
    }
  }
  return { tier: 'free', cost: '—', format: '' };
}

export function RoutingPage() {
  const { data, error, reload } = useData(() => routingSummary(), 5000);
  const [showForm, setShowForm] = useState(false);
  const [added, setAdded] = useState('');
  const [actionError, setActionError] = useState('');
  const [provider, setProvider] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [priority, setPriority] = useState('0');

  useScreenInput((k) => {
    if (k.q || k.up || k.down || k.esc) return false;
    if (showForm) return false;
    if (k.input === 'a') {
      setShowForm(true);
      return true;
    }
    return false;
  });

  function addAccount() {
    try {
      const id = accountManager.add_account(provider.trim(), apiKey.trim() || null, baseUrl.trim() || null, Number(priority) || 0);
      setAdded(`Added ${id}`);
      setApiKey('');
      setBaseUrl('');
      setShowForm(false);
      reload();
    } catch (e) {
      setActionError(String((e as Error).message || e));
    }
  }

  return (
    <Page title="Routing" sub="How requests are routed to providers, with fallback chains.">
      {error && <ErrorLine>{error}</ErrorLine>}
      {actionError && <ErrorLine>{actionError}</ErrorLine>}
      {!data && !error && <Hint>Loading…</Hint>}
      {data && (
        <>
          <Row>
            <Stat label="Current model" value={data.currentModel || '—'} />
            <Stat
              label="Upstream target"
              value={data.upstream ? data.upstream.url : 'direct (no proxy)'}
              sub={data.upstream ? `via ${data.upstream.pid}` : 'resolved upstream URL'}
            />
            <Stat label="Provider tier" value={data.tier || '—'} sub="subscription / cheap / free" />
            <Stat
              label="Accounts"
              value={fmt(data.accounts?.length ?? 0)}
              sub={`strategy: ${data.accountStrategy || 'round-robin'}`}
            />
          </Row>
          {added && <SuccessLine>{added}</SuccessLine>}
          <Hint>Press a to add an account (rotates API keys through the proxy).</Hint>
          {showForm && (
            <Form
              title="Add account"
              fields={[
                { label: 'Provider', get: () => provider, set: setProvider },
                { label: 'API key', get: () => apiKey, set: setApiKey },
                { label: 'Base URL (optional)', get: () => baseUrl, set: setBaseUrl },
                { label: 'Priority (0 first)', get: () => priority, set: setPriority },
              ]}
              onDone={addAccount}
              onCancel={() => setShowForm(false)}
            />
          )}
          <Section title="Tiered fallback chain">
            {data.tieredChain?.length ? (
              <Table
                head={['#', 'Provider', 'Tier', 'Cost', 'Endpoint format']}
                rows={data.tieredChain.map((p, i) => {
                  const meta = getProviderMeta(p);
                  return [T(i + 1), T(p), T(meta.tier), T(meta.cost), T(meta.format || '—')];
                })}
              />
            ) : (
              <Hint>
                No lower-tier fallbacks for {data.currentModel?.split('/')[0] || 'the current provider'} (already in
                the cheapest tier).
              </Hint>
            )}
          </Section>
          <Section title="Per-model fallback chain">
            {data.fallbackChain.length ? (
              <Table head={['#', 'Fallback model']} rows={data.fallbackChain.map((m, i) => [T(i + 1), T(m)])} />
            ) : (
              <Hint>No fallback chain configured for {data.currentModel || 'the current model'}.</Hint>
            )}
          </Section>
          <Section title="Provider routing">
            <Table
              head={['Provider', 'Configured', 'Proxied', 'Base URL']}
              rows={data.routing.map((r) => [
                T(r.provider),
                T(r.configured ? 'cfg' : '—', r.configured ? 'green' : undefined),
                T(r.proxied ? 'proxy' : '—', r.proxied ? 'green' : undefined),
                T(r.baseURL || '—'),
              ])}
            />
          </Section>
          <Section title="Upstreams">
            <Table
              head={['Provider', 'Upstream URL']}
              rows={Object.entries(data.upstreams).map(([pid, url]) => [T(pid), T(url)])}
            />
          </Section>
          <Section title="Accounts">
            {data.accounts?.length ? (
              <Table
                head={['ID', 'Provider', 'Status', 'Priority']}
                rows={data.accounts.map((a) => [
                  T(a.id),
                  T(a.provider),
                  T(a.status === 'rate_limited' ? a.status : 'active', a.status === 'rate_limited' ? 'red' : 'green'),
                  T(fmt(a.priority)),
                ])}
              />
            ) : (
              <Hint>
                No accounts yet. Add one to rotate multiple API keys through the proxy (uses the account's base URL and
                API key).
              </Hint>
            )}
          </Section>
        </>
      )}
    </Page>
  );
}
