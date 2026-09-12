import React, { useCallback, useEffect, useState } from 'react';
import { Page, Row, Stat, Hint, ErrorLine, TextField, fmt, uptime } from '../components.js';
import { useScreenInput } from '../input.js';
import * as proxy from '../../core/proxy.js';
import type { ProxyStatus } from '../../core/types.js';

export function ProxyPage() {
  const [status, setStatus] = useState<ProxyStatus | null>(null);
  const [error, setError] = useState('');
  const [port, setPort] = useState(String(proxy.DEFAULT_PORT));
  const [editPort, setEditPort] = useState(false);
  const [test, setTest] = useState<any>(null);

  const refresh = useCallback(() => {
    try {
      setStatus(proxy.status());
      setError('');
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (status && status.port) setPort(String(status.port));
  }, [status]);

  const doAction = useCallback(
    (fn: () => Promise<unknown>) => {
      setError('');
      Promise.resolve()
        .then(() => fn())
        .then(refresh)
        .catch((e) => setError(String((e as Error).message || e)));
    },
    [refresh]
  );

  function runTest() {
    setError('');
    Promise.resolve()
      .then(() => proxy.testConnection())
      .then(setTest)
      .catch((e) => setError(String((e as Error).message || e)));
  }

  useScreenInput((k) => {
    if (k.q || k.up || k.down || k.esc) return false;
    if (editPort) return false;
    if (k.enter) {
      if (running) doAction(() => proxy.stop());
      else doAction(() => proxy.start(Number(port)));
      return true;
    }
    switch (k.input) {
      case 'p':
        setEditPort(true);
        return true;
      case 's':
        doAction(() => proxy.start(Number(port)));
        return true;
      case 't':
        doAction(() => proxy.stop());
        return true;
      case 'e':
        doAction(async () => {
          proxy.enable(true, Number(port));
        });
        return true;
      case 'd':
        doAction(async () => {
          proxy.enable(false);
        });
        return true;
      case 'c':
        runTest();
        return true;
      default:
        return false;
    }
  });

  const running = !!status?.running;
  const actualPort = status?.port ?? port;

  return (
    <Page
      title="Proxy"
      sub={`Local HTTP proxy on port ${actualPort} that routes requests to the upstream provider and compresses outgoing tool results with RTK filters.`}
    >
      {error && <ErrorLine>{error}</ErrorLine>}
      {!status && !error && <Hint>Loading…</Hint>}
      {status && (
        <>
          <Row>
            <Stat
              label="Status"
              value={running ? 'Running' : 'Stopped'}
              color={running ? 'green' : 'red'}
              sub={running ? uptime(status.startedAt) : 'not listening'}
            />
            <Stat label="Auto-start" value={status.enabled ? 'Enabled' : 'Disabled'} />
            <Stat label="Requests" value={fmt(status.requestsServed ?? 0)} sub="POSTs through the proxy" />
            <Stat label="Compression hits" value={fmt(status.compressionHits ?? 0)} />
            <Stat label="Bytes saved" value={`${fmt(status.totalSavedBytes ?? 0)}B`} />
          </Row>
          {status.lastModel && <Hint>Last model routed: {status.lastModel}</Hint>}
          <Hint>
            Enter: toggle start/stop · s: start · t: stop · e: enable auto-start · d: disable · c: test connection · p: edit port · q: quit
          </Hint>
          {editPort && (
            <TextField
              label="Port"
              value={port}
              onChange={setPort}
              onSubmit={() => setEditPort(false)}
              onCancel={() => setEditPort(false)}
              placeholder="8199"
            />
          )}
          {test && (
            <Row>
              {test.running === false ? (
                <Stat label="Connection test" value="Proxy is not running" sub="" />
              ) : (
                <>
                  <Stat
                    label="Proxy health"
                    value={test.health.ok ? `HTTP ${test.health.code} OK` : `HTTP ${test.health.code ?? 'no response'}`}
                    color={test.health.ok ? 'green' : 'red'}
                    sub={test.health.ok ? undefined : test.health.error}
                  />
                  {test.forward ? (
                    <Stat
                      label="Upstream forward"
                      value={test.forward.code >= 500 ? `HTTP ${test.forward.code}` : `HTTP ${test.forward.code}`}
                      color={test.forward.code >= 400 ? 'red' : 'green'}
                      sub={
                        test.forward.upstream
                          ? test.forward.upstream + (test.forward.code === 401 ? ' — proxy reached the upstream; add your API key to the client' : '')
                          : test.forward.error || undefined
                      }
                    />
                  ) : (
                    <Stat label="Upstream forward" value="no response" />
                  )}
                </>
              )}
            </Row>
          )}
          {running && <Hint>Point your client at http://127.0.0.1:{actualPort}/v1 and it will be routed through this proxy.</Hint>}
          {status.proxiedProviders && status.proxiedProviders.length > 0 && (
            <Row>
              <Stat label="Proxied providers" value={status.proxiedProviders.join(', ')} />
              {Object.entries(status.upstreams || {}).map(([pid, url]) => (
                <Stat key={pid} label={pid} value={url} />
              ))}
            </Row>
          )}
        </>
      )}
    </Page>
  );
}
