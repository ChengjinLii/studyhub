import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

export type AppToastTone = 'info' | 'loading' | 'success' | 'warning' | 'error';

interface AppToastOptions {
  id?: string;
  tone?: AppToastTone;
  duration?: number;
}

interface AppToastItem {
  id: string;
  message: string;
  tone: AppToastTone;
}

interface AppToastApi {
  show: (message: string, options?: AppToastOptions) => string;
  dismiss: (id: string) => void;
}

const AppToastContext = createContext<AppToastApi | null>(null);
const NEXT_TOAST_KEY = 'studyhub:next-toast:v1';
const DEFAULT_DURATION: Record<AppToastTone, number> = {
  info: 3200,
  loading: 0,
  success: 2800,
  warning: 5200,
  error: 5600,
};

const createToastId = () => `toast-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

export const queueNextAppToast = (message: string, tone: Exclude<AppToastTone, 'loading'> = 'success') => {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(NEXT_TOAST_KEY, JSON.stringify({ message, tone }));
  } catch {
    // The current-page toast still provides feedback when storage is unavailable.
  }
};

export function AppToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<AppToastItem[]>([]);
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer) clearTimeout(timer);
    timersRef.current.delete(id);
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const show = useCallback<AppToastApi['show']>(
    (message, options = {}) => {
      const id = options.id || createToastId();
      const tone = options.tone || 'info';
      const duration = options.duration ?? DEFAULT_DURATION[tone];
      const existingTimer = timersRef.current.get(id);
      if (existingTimer) clearTimeout(existingTimer);

      setItems((current) => {
        const nextItem = { id, message, tone };
        const existingIndex = current.findIndex((item) => item.id === id);
        const next = existingIndex >= 0
          ? current.map((item) => (item.id === id ? nextItem : item))
          : [...current, nextItem];
        return next.slice(-4);
      });

      if (duration > 0) {
        const timer = setTimeout(() => dismiss(id), duration);
        timersRef.current.set(id, timer);
      } else {
        timersRef.current.delete(id);
      }
      return id;
    },
    [dismiss]
  );

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
    };
  }, []);

  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(NEXT_TOAST_KEY);
      if (!raw) return;
      window.sessionStorage.removeItem(NEXT_TOAST_KEY);
      const queued = JSON.parse(raw) as { message?: unknown; tone?: unknown };
      if (typeof queued.message !== 'string' || !queued.message.trim()) return;
      const tone = ['info', 'success', 'warning', 'error'].includes(String(queued.tone))
        ? queued.tone as Exclude<AppToastTone, 'loading'>
        : 'success';
      show(queued.message, { tone });
    } catch {
      // Ignore unavailable or malformed session storage.
    }
  }, [show]);

  const value = useMemo(() => ({ show, dismiss }), [dismiss, show]);

  return (
    <AppToastContext.Provider value={value}>
      {children}
      <div className="app-toast-region" aria-live="polite" aria-atomic="false">
        {items.map((item) => (
          <div
            key={item.id}
            className={`app-toast app-toast--${item.tone}`}
            role={item.tone === 'error' ? 'alert' : 'status'}
          >
            <span className="app-toast__icon" aria-hidden="true">
              {item.tone === 'loading' ? (
                <span className="app-toast__spinner" />
              ) : item.tone === 'success' ? (
                <svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6" /></svg>
              ) : item.tone === 'error' ? (
                <svg viewBox="0 0 24 24"><path d="M7 7l10 10M17 7 7 17" /></svg>
              ) : item.tone === 'warning' ? (
                <svg viewBox="0 0 24 24"><path d="M12 4 3 20h18L12 4Zm0 6v4m0 3h.01" /></svg>
              ) : (
                <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10h.01" /></svg>
              )}
            </span>
            <span className="app-toast__message">{item.message}</span>
            {item.tone !== 'loading' && (
              <button type="button" className="app-toast__close" aria-label="关闭提示" onClick={() => dismiss(item.id)}>
                ×
              </button>
            )}
          </div>
        ))}
      </div>
    </AppToastContext.Provider>
  );
}

export function useAppToast() {
  const context = useContext(AppToastContext);
  if (!context) throw new Error('useAppToast must be used within AppToastProvider');
  return context;
}
