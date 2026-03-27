import Link from 'next/link';
import { useRouter } from 'next/router';
import { useState } from 'react';
import { hasRole } from '../lib/auth';
import { fetchBackend } from '../lib/apiBase';
import { RoleMask, SessionUser } from '../types/user';

interface NavBarProps {
  user: SessionUser | null;
}

export default function NavBar({ user }: NavBarProps) {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const loginTarget =
    user || !router.asPath ? '/login' : `/login?next=${encodeURIComponent(router.asPath)}`;
  const displayName = user?.nickname || user?.username || '';
  const shortName = displayName.length > 5 ? `${displayName.slice(0, 5)}..` : displayName;

  const handleLogout = async () => {
    setSubmitting(true);
    await fetchBackend('/logout', { method: 'POST' });
    router.replace('/');
  };

  return (
    <header className="site-header">
      <div className="container header-content">
        <div className="header-top">
          <div className="header-brand">
            <h1 className="site-title">
              <Link href="/">
                <span className="title-en">StudyHub</span>
                <span className="title-dot"> · </span>
                <span className="title-cn">学汇</span>
              </Link>
            </h1>
          </div>
          <nav className="main-nav">
            <Link href="/">首页</Link>
            <Link href="/column">学汇专栏</Link>
            <Link href="/market">校园集市</Link>
            <Link href="/upload">我要投稿</Link>
            <Link href="/join">关于我们</Link>
            {user && (hasRole(user.roleMask, RoleMask.ADMIN) || hasRole(user.roleMask, RoleMask.DEVELOPER)) && (
              <Link href="/admin">管理后台</Link>
            )}
            <Link href="/me">我的</Link>
          </nav>
          <div className="auth-actions">
            {user ? (
              <div className="user-pill">
                <span className="user-pill__name">{shortName}</span>
                <button className="button ghost small" onClick={handleLogout} disabled={submitting}>
                  退出
                </button>
              </div>
            ) : (
              <>
                <span className="user-pill">游客模式</span>
                <Link className="button ghost" href={loginTarget}>
                  登录 / 注册
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
