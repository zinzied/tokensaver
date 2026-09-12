import React, { useCallback, useState } from 'react';
import { Box, Text } from 'ink';
import { InputProvider, type KeyEvent } from './input.js';
import { OverviewPage } from './pages/OverviewPage.js';
import { UsagePage } from './pages/UsagePage.js';
import { QuotaPage } from './pages/QuotaPage.js';
import { CompressPage } from './pages/CompressPage.js';
import { ProxyPage } from './pages/ProxyPage.js';
import { RoutingPage } from './pages/RoutingPage.js';
import { ProvidersPage } from './pages/ProvidersPage.js';
import { ModelsPage } from './pages/ModelsPage.js';
import { SearchPage } from './pages/SearchPage.js';
import { TodoPage } from './pages/TodoPage.js';
import { GoalsPage } from './pages/GoalsPage.js';
import { SettingsPage } from './pages/SettingsPage.js';
import { APP_NAME } from '../banner.js';

export const NAV = [
  { id: 'overview', label: 'Overview' },
  { id: 'usage', label: 'Usage' },
  { id: 'quota', label: 'Quota' },
  { id: 'compress', label: 'Compress' },
  { id: 'proxy', label: 'Proxy' },
  { id: 'routing', label: 'Routing' },
  { id: 'providers', label: 'Providers' },
  { id: 'models', label: 'Models' },
  { id: 'search', label: 'Search' },
  { id: 'todo', label: 'Todo' },
  { id: 'goals', label: 'Goals' },
  { id: 'settings', label: 'Settings' },
];

function Sidebar({ active }: { active: number }) {
  return (
    <Box flexDirection="column" width={18} paddingTop={1} paddingLeft={1} paddingRight={1}>
      <Text bold color="magenta">
        {APP_NAME}
      </Text>
      <Text color="gray">v10.0.0</Text>
      <Box flexDirection="column" marginTop={1}>
        {NAV.map((item, i) => (
          <Text key={item.id} color={i === active ? 'cyan' : 'gray'} bold={i === active}>
            {i === active ? '› ' : '  '}
            {item.label}
          </Text>
        ))}
      </Box>
    </Box>
  );
}

function Shell({ onExit }: { onExit: () => void }) {
  const [active, setActive] = useState(0);

  const handleGlobal = useCallback(
    (k: KeyEvent) => {
      if (k.q) {
        onExit();
        return;
      }
      if (k.up) setActive((a) => (a - 1 + NAV.length) % NAV.length);
      else if (k.down) setActive((a) => (a + 1) % NAV.length);
    },
    [onExit]
  );

  const pages = [
    <OverviewPage key="overview" />,
    <UsagePage key="usage" />,
    <QuotaPage key="quota" />,
    <CompressPage key="compress" />,
    <ProxyPage key="proxy" />,
    <RoutingPage key="routing" />,
    <ProvidersPage key="providers" />,
    <ModelsPage key="models" />,
    <SearchPage key="search" />,
    <TodoPage key="todo" />,
    <GoalsPage key="goals" />,
    <SettingsPage key="settings" />,
  ];

  return (
    <InputProvider onKey={handleGlobal}>
      <Box flexDirection="row" flexGrow={1}>
        <Sidebar active={active} />
        <Box flexDirection="column" flexGrow={1} borderStyle="round" borderColor="cyan">
          {pages[active]}
        </Box>
      </Box>
      <Box paddingLeft={1} paddingBottom={1}>
        <Text color="gray">
          Up/Down: navigate · q: quit · Esc: back/cancel. Pages with inputs accept Enter/Esc.
        </Text>
      </Box>
    </InputProvider>
  );
}

export default function App({ onExit }: { onExit?: () => void }) {
  const exit = useCallback(() => {
    if (onExit) onExit();
    else process.exit(0);
  }, [onExit]);
  return <Shell onExit={exit} />;
}
