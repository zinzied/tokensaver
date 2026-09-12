import React from 'react';
import { Box, Text } from 'ink';
import { Page, Section, Hint, Table, T } from '../components.js';
import { useData } from '../useData.js';
import { loadTodo, type TodoItem } from '../../core/todo.js';

const STATUS_ICON: Record<string, string> = {
  pending: '\u25cb',
  done: '\u2713',
  cancelled: '\u2717',
};

const STATUS_COLOR: Record<string, string> = {
  pending: 'yellow',
  done: 'green',
  cancelled: 'red',
};

export function TodoPage() {
  const { data, error } = useData(() => loadTodo(), 3000);
  const items = data?.items || [];
  const pending = items.filter((i) => i.status === 'pending');
  const done = items.filter((i) => i.status === 'done');
  const cancelled = items.filter((i) => i.status === 'cancelled');

  return (
    <Page title="Todo" sub="Session task tracker.">
      {error && <Text color="red">{error}</Text>}
      {!data && !error && <Hint>Loading…</Hint>}
      {data && (
        <>
          <Section title={`Pending (${pending.length})`}>
            {pending.length === 0 ? (
              <Hint>No pending tasks.</Hint>
            ) : (
              <Table
                head={['', 'ID', 'Task', 'Created']}
                rows={pending.map((item) => [
                  T(STATUS_ICON[item.status], STATUS_COLOR[item.status]),
                  T(item.id, 'gray'),
                  T(item.text),
                  T(new Date(item.created).toLocaleString(), 'gray'),
                ])}
              />
            )}
          </Section>
          {done.length > 0 && (
            <Section title={`Done (${done.length})`}>
              <Table
                head={['', 'ID', 'Task', 'Completed']}
                rows={done.map((item) => [
                  T(STATUS_ICON[item.status], STATUS_COLOR[item.status]),
                  T(item.id, 'gray'),
                  T(item.text),
                  T(new Date(item.updated).toLocaleString(), 'gray'),
                ])}
              />
            </Section>
          )}
          {cancelled.length > 0 && (
            <Section title={`Cancelled (${cancelled.length})`}>
              <Table
                head={['', 'ID', 'Task', 'Cancelled']}
                rows={cancelled.map((item) => [
                  T(STATUS_ICON[item.status], STATUS_COLOR[item.status]),
                  T(item.id, 'gray'),
                  T(item.text),
                  T(new Date(item.updated).toLocaleString(), 'gray'),
                ])}
              />
            </Section>
          )}
          <Box marginTop={1}>
            <Text color="gray">
              {pending.length} pending · {done.length} done · {cancelled.length} cancelled
            </Text>
          </Box>
        </>
      )}
    </Page>
  );
}
