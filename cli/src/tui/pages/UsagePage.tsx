import React from 'react';
import { Page, Section, Row, Stat, Table, Hint, ErrorLine, fmt, T } from '../components.js';
import { useData } from '../useData.js';
import { usageSummary } from '../../core/insights.js';

export function UsagePage() {
  const { data, error } = useData(() => usageSummary(), 3000);
  return (
    <Page title="Usage" sub="Savings ledger and proxy request history (live — refreshes every 3s).">
      {error && <ErrorLine>{error}</ErrorLine>}
      {!data && !error && <Hint>Loading…</Hint>}
      {data && (
        <>
          <Row>
            <Stat label="Ledger entries" value={fmt(data.ledger.entries)} />
            <Stat label="Raw tokens" value={fmt(data.ledger.raw_tokens)} />
            <Stat label="Tokens saved" value={fmt(data.ledger.saved_tokens)} />
            <Stat label="Proxy requests" value={fmt(data.proxy.requests)} />
            <Stat label="Proxy tokens saved" value={fmt(data.proxy.saved_tokens)} />
            <Stat label="Proxy bytes saved" value={`${fmt(data.proxy.saved_bytes)}B`} />
            <Stat label="Frost saved" value={fmt(data.proxy.frost_saved)} />
          </Row>
          <Section title="By kind">
            <Table
              head={['Kind', 'Count', 'Tokens saved']}
              rows={data.byKind.map((k) => [T(k.kind), T(fmt(k.count)), T(fmt(k.saved_tokens))])}
            />
          </Section>
          <Section title="By model">
            <Table
              head={['Model', 'Requests', 'Tokens saved', 'Bytes saved']}
              rows={data.perModel.map((m) => [T(m.model), T(fmt(m.requests)), T(fmt(m.saved_tokens)), T(`${fmt(m.saved_bytes)}B`)])}
            />
          </Section>
          <Section title="Recent activity">
            <Table
              head={['Time', 'Kind', 'Description', 'Saved']}
              rows={data.recent.map((r) => [T(r.ts), T(r.kind), T(r.description), T(`${fmt(r.saved)}${r.unit}`)])}
            />
          </Section>
        </>
      )}
    </Page>
  );
}
