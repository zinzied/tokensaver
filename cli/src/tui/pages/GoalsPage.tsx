import React from 'react';
import { Box, Text } from 'ink';
import { Page, Section, Hint, Table, T } from '../components.js';
import { useData } from '../useData.js';
import { loadGoals, type Goal } from '../../core/goals.js';

const STATUS_ICON: Record<string, string> = {
  active: '\u25b6',
  completed: '\u2713',
  abandoned: '\u2717',
};

const STATUS_COLOR: Record<string, string> = {
  active: 'cyan',
  completed: 'green',
  abandoned: 'red',
};

export function GoalsPage() {
  const { data, error } = useData(() => loadGoals(), 3000);
  const goals = data?.goals || [];
  const active = goals.filter((g) => g.status === 'active');
  const completed = goals.filter((g) => g.status === 'completed');
  const abandoned = goals.filter((g) => g.status === 'abandoned');

  return (
    <Page title="Goals" sub="Session-level objectives tracker.">
      {error && <Text color="red">{error}</Text>}
      {!data && !error && <Hint>Loading…</Hint>}
      {data && (
        <>
          <Section title={`Active (${active.length})`}>
            {active.length === 0 ? (
              <Hint>No active goals.</Hint>
            ) : (
              <Table
                head={['', 'ID', 'Goal', 'Created']}
                rows={active.map((g) => [
                  T(STATUS_ICON[g.status], STATUS_COLOR[g.status]),
                  T(g.id, 'gray'),
                  T(g.text),
                  T(new Date(g.created).toLocaleString(), 'gray'),
                ])}
              />
            )}
          </Section>
          {completed.length > 0 && (
            <Section title={`Completed (${completed.length})`}>
              <Table
                head={['', 'ID', 'Goal', 'Completed']}
                rows={completed.map((g) => [
                  T(STATUS_ICON[g.status], STATUS_COLOR[g.status]),
                  T(g.id, 'gray'),
                  T(g.text),
                  T(new Date(g.updated).toLocaleString(), 'gray'),
                ])}
              />
            </Section>
          )}
          {abandoned.length > 0 && (
            <Section title={`Abandoned (${abandoned.length})`}>
              <Table
                head={['', 'ID', 'Goal', 'Abandoned']}
                rows={abandoned.map((g) => [
                  T(STATUS_ICON[g.status], STATUS_COLOR[g.status]),
                  T(g.id, 'gray'),
                  T(g.text),
                  T(new Date(g.updated).toLocaleString(), 'gray'),
                ])}
              />
            </Section>
          )}
          <Box marginTop={1}>
            <Text color="gray">
              {active.length} active · {completed.length} completed · {abandoned.length} abandoned
            </Text>
          </Box>
        </>
      )}
    </Page>
  );
}
