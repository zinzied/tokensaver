import React from 'react';
import { Box, Text } from 'ink';
import { Page, Row, Stat, Hint, ErrorLine, fmt } from '../components.js';
import { useData } from '../useData.js';
import { usageSummary } from '../../core/insights.js';
import { BANNER, APP_NAME } from '../../banner.js';

export function OverviewPage() {
  const { data: p, error } = useData(() => usageSummary(), 3000);
  return (
    <Page title={APP_NAME} sub="v10.0.0 — reduce token waste and spending when using AI coding models">
      <Box>
        <Text color="magenta" bold>
          {BANNER}
        </Text>
      </Box>
      {error && <ErrorLine>{error}</ErrorLine>}
      {p && (
        <Row>
          <Stat label="Ledger entries" value={fmt(p.ledger.entries)} />
          <Stat label="Ledger tokens saved" value={fmt(p.ledger.saved_tokens)} />
          <Stat label="Proxy requests" value={fmt(p.proxy.requests)} />
          <Stat label="Proxy tokens saved" value={fmt(p.proxy.saved_tokens)} />
        </Row>
      )}
      <Hint>
        Pick a page from the sidebar (Up/Down to move, q to quit): Usage, Quota, Compress, Proxy, Routing,
        Providers, Models, Search or Settings.
      </Hint>
    </Page>
  );
}
