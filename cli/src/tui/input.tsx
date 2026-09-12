import { createContext, useContext, useEffect, useRef, type ReactNode } from 'react';
import { useInput, type Key } from 'ink';

export interface KeyEvent {
  input: string;
  up: boolean;
  down: boolean;
  left: boolean;
  right: boolean;
  enter: boolean;
  esc: boolean;
  backspace: boolean;
  delete: boolean;
  tab: boolean;
  shiftTab: boolean;
  ctrl: boolean;
  q: boolean;
}

export type KeyHandler = (k: KeyEvent) => boolean;

function normalize(input: string, key: Key): KeyEvent {
  return {
    input,
    up: key.upArrow,
    down: key.downArrow,
    left: key.leftArrow,
    right: key.rightArrow,
    enter: key.return,
    esc: key.escape,
    backspace: key.backspace,
    delete: key.delete,
    tab: key.tab,
    shiftTab: !!(key.shift && key.tab),
    ctrl: !!key.ctrl,
    q: input === 'q' && !key.ctrl,
  };
}

interface InputContextValue {
  push: (h: KeyHandler) => void;
  pop: (h: KeyHandler) => void;
}

const InputContext = createContext<InputContextValue>({ push: () => {}, pop: () => {} });

export function InputProvider({ children, onKey }: { children: ReactNode; onKey: (k: KeyEvent) => void }) {
  const stack = useRef<KeyHandler[]>([]);
  const push = (h: KeyHandler) => {
    stack.current.push(h);
  };
  const pop = (h: KeyHandler) => {
    stack.current = stack.current.filter((x) => x !== h);
  };

  const interactive = process.stdin.isTTY === true && process.stdout.isTTY === true;

  useInput(
    (input, key) => {
      const k = normalize(input, key);
      const s = stack.current;
      for (let i = s.length - 1; i >= 0; i--) {
        if (s[i](k)) return;
      }
      onKey(k);
    },
    { isActive: interactive }
  );

  return <InputContext.Provider value={{ push, pop }}>{children}</InputContext.Provider>;
}

export function useScreenInput(handler: KeyHandler) {
  const { push, pop } = useContext(InputContext);
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const wrapped = (k: KeyEvent) => ref.current(k);
    push(wrapped);
    return () => pop(wrapped);
  }, [push, pop]);
}
