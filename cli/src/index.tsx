import React from 'react';
import { render, Text } from 'ink';
import App from './tui/App.js';
import { runCommand } from './cli/commands.js';
import { TS_VERSION } from './core/config.js';
import { APP_NAME } from './banner.js';

function parseArgv(argv: string[]): { command: string[]; wantsTui: boolean } {
  const command: string[] = [];
  let wantsTui = false;
  for (const a of argv) {
    if (a === '--tui' || a === '-i' || a === 'tui') wantsTui = true;
    else if (a === '--help' || a === '-h' || a === 'help') {
      wantsTui = false;
      command.push(a === 'help' ? 'help' : '--help');
    } else command.push(a);
  }
  return { command, wantsTui };
}

async function main() {
  const { command, wantsTui } = parseArgv(process.argv.slice(2));

  const isPiped = !process.stdin.isTTY;
  const interactive = process.stdin.isTTY === true && process.stdout.isTTY === true;
  if (wantsTui || (!command.length && interactive)) {
    if (!interactive) {
      console.log(`${APP_NAME} CLI v${TS_VERSION} — the TUI needs an interactive terminal. Run "token-saver help" for CLI commands.`);
      return;
    }
    render(<App />);
    return;
  }
  if (!command.length && isPiped) {
    console.log(`${APP_NAME} CLI v${TS_VERSION} — pipe a subcommand (see "token-saver help").`);
    return;
  }
  const code = await runCommand(command);
  if (code !== 0) process.exitCode = code;
}

main().catch((e) => {
  console.error(String((e as Error).message || e));
  process.exitCode = 1;
});
