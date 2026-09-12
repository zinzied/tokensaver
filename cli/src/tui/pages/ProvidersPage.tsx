import React from 'react';
import { Page, Table, Hint, ErrorLine, T } from '../components.js';
import { useData } from '../useData.js';
import { providersList } from '../../core/insights.js';

const SOURCE_KEYS: [string, string][] = [
  ['configured', 'cfg'],
  ['working', 'work'],
  ['envDetected', 'env'],
  ['authDetected', 'auth'],
  ['inHistory', 'history'],
];

export function ProvidersPage() {
  const { data, error } = useData(() => providersList());
  return (
    <Page title="Providers" sub={data ? `Detected and configured providers (${data.length} total).` : undefined}>
      {error && <ErrorLine>{error}</ErrorLine>}
      {!data && !error && <Hint>Loading…</Hint>}
      {data && (
        <Table
          head={['Provider', 'Sources', 'Proxied', 'Base URL', 'Env vars']}
          rows={data.map((p) => [
            T(p.provider),
            T(
              SOURCE_KEYS.filter(([k]) => (p as any)[k]).map(([, label]) => label).join(' ') || '—',
              SOURCE_KEYS.some(([k]) => (p as any)[k]) ? 'green' : undefined
            ),
            T(p.proxied ? 'proxy' : '—', p.proxied ? 'green' : undefined),
            T(p.baseURL || '—'),
            T(p.envVars.length ? p.envVars.join('  ') : '—'),
          ])}
        />
      )}
    </Page>
  );
}
