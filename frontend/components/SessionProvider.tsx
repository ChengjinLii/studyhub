import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { readSession } from '../lib/auth';
import { SessionUser } from '../types/user';

interface SessionContextValue {
  user: SessionUser | null;
  refreshSession: () => SessionUser | null;
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
  const [user, setUser] = useState<SessionUser | null>(() =>
    initialUser === undefined ? readSession().user : initialUser
  );

  const refreshSession = useCallback(() => {
    const nextUser = readSession().user;
    setUser((current) => (sameSessionUser(current, nextUser) ? current : nextUser));
    return nextUser;
  }, []);

  useEffect(() => {
    const nextUser = initialUser === undefined ? readSession().user : initialUser;
    setUser((current) => (sameSessionUser(current, nextUser) ? current : nextUser));
  }, [initialUser]);

  useEffect(() => {
    const handleSessionRefresh = () => {
      refreshSession();
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refreshSession();
      }
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
