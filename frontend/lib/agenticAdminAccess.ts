import { GetServerSidePropsContext } from 'next';
import { hasRole, readSession, SessionState } from './auth';
import { RoleMask } from '../types/user';

export const resolveAgenticAdminAccess = (ctx: GetServerSidePropsContext, next: string) => {
  const session: SessionState = readSession(ctx.req);
  if (session.user && hasRole(session.user.roleMask, RoleMask.ADMIN)) {
    return { session, redirect: null };
  }
  return {
    session,
    redirect: {
      destination: session.user ? '/admin' : `/login?next=${encodeURIComponent(next)}`,
      permanent: false,
    },
  };
};
