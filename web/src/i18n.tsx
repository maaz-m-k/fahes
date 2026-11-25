import { createContext, useContext } from 'react';
import type { Bi, Lang } from './api/types';
import type { EngineClient } from './api/client';

export const LangContext = createContext<Lang>('ar');
export function useLang() {
  const lang = useContext(LangContext);
  return { lang, ar: lang === 'ar', t: (b: Bi | null | undefined) => (b ? b[lang] ?? b.ar : ''), tx: (ar: string, en: string) => (lang === 'ar' ? ar : en) };
}

export const EngineContext = createContext<EngineClient | null>(null);
export function useEngine(): EngineClient {
  const c = useContext(EngineContext);
  if (!c) throw new Error('no engine client');
  return c;
}

export const fmt = (n: number | null | undefined) => (n == null ? '…' : Math.round(Number(n)).toLocaleString('en-US'));
export const clock = (ms: number) => new Date(ms).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Dubai' });
