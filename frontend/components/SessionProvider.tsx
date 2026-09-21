import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { fetchBackend } from '../lib/apiBase';
import { SessionUser } from '../types/user';

interface SessionContextValue {
  user: SessionUser | null;
  refreshSession: () => Promise<SessionUser | null>;
}

interface SessionResponse {
  ok?: boolean;
  data?: {
    user?: SessionUser | null;
  };
}

const SessionContext = createContext<SessionContextValue | null>(null);

const sameSessionUser = (current: SessionUser | null, next: SessionUser | null) =>
  current?.id === next?.id &&
  current?.roleMask === next?.roleMask &&
  current?.nickname === next?.nickname &&
  current?.username === next?.username &&
  current?.avatar === next?.avatar &&
  current?.email === next?.email &&
  current?.verified === next?.verified &&
  current?.freeDownloadQuota === next?.freeDownloadQuota &&
  current?.emailPrivacy === next?.emailPrivacy;

export function SessionProvider({
  children,
  initialUser,
}: {
  children: ReactNode;
  initialUser?: SessionUser | null;
}) {
  const [user, setUser] = useState<SessionUser | null>(initialUser ?? null);
  const refreshSequence = useRef(0);

  const applyUser = useCallback((nextUser: SessionUser | null) => {
    setUser((current) => (sameSessionUser(current, nextUser) ? current : nextUser));
  }, []);

  const refreshSession = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    try {
      const response = await fetchBackend('/session', { cache: 'no-store' });
      if (sequence !== refreshSequence.current) return null;
      if (response.status === 401 || response.status === 403) {
        applyUser(null);
        return null;
      }
      if (!response.ok) return null;
      const payload = (await response.json()) as SessionResponse;
      const nextUser = payload.ok ? payload.data?.user ?? null : null;
      applyUser(nextUser);
      return nextUser;
    } catch {
      // Keep the last known session during temporary network failures.
      return null;
    }
  }, [applyUser]);

  useEffect(() => {
    if (initialUser !== undefined) applyUser(initialUser);
    void refreshSession();
  }, [applyUser, initialUser, refreshSession]);

  useEffect(() => {
    const handleSessionRefresh = () => {
      void refreshSession();
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') void refreshSession();
    };

    window.addEventListener('focus', handleSessionRefresh);
    window.addEventListener('studyhub:session-changed', handleSessionRefresh);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.removeEventListener('focus', handleSessionRefresh);
      window.removeEventListener('studyhub:session-changed', handleSessionRefresh);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [refreshSession]);

  const value = useMemo(() => ({ user, refreshSession }), [refreshSession, user]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within SessionProvider');
  }
  return context;
}
