import Link from 'next/link';
import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import BrandLogo from './BrandLogo';
import { hasRole } from '../lib/auth';
import { fetchBackend } from '../lib/apiBase';
import { RoleMask, SessionUser } from '../types/user';
import styles from '../styles/AnimateHeader.module.css';

interface NavBarProps {
  user: SessionUser | null;
}

const GITHUB_REPO_OWNER = 'ChengjinLii';
const GITHUB_REPO_NAME = 'studyhub';
const GITHUB_REPO_URL = `https://github.com/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}`;
const GITHUB_API_URL = `https://api.github.com/repos/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}`;
const STARS_CACHE_KEY = 'studyhub:github-stars-v1';
const STARS_CACHE_TTL_MS = 10 * 60 * 1000;

function formatStarCount(count: number): string {
  if (!Number.isFinite(count) || count < 0) return '0';
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  }
  return String(Math.floor(count));
}

export default function NavBar({ user }: NavBarProps) {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [githubStars, setGithubStars] = useState<number | null>(null);
  const loginTarget =
    user || !router.asPath ? '/login' : `/login?next=${encodeURIComponent(router.asPath)}`;
  const displayName = user?.nickname || user?.username || '';
  const shortName = displayName.length > 5 ? `${displayName.slice(0, 5)}..` : displayName;
  const isStaff = Boolean(
    user && (hasRole(user.roleMask, RoleMask.ADMIN) || hasRole(user.roleMask, RoleMask.DEVELOPER))
  );

  useEffect(() => {
    let active = true;
    try {
      const cachedRaw = window.sessionStorage.getItem(STARS_CACHE_KEY);
      if (cachedRaw) {
        const cached = JSON.parse(cachedRaw) as { stars?: number; ts?: number };
        if (
          typeof cached.stars === 'number' &&
          typeof cached.ts === 'number' &&
          Date.now() - cached.ts < STARS_CACHE_TTL_MS
        ) {
          setGithubStars(cached.stars);
          return () => {
            active = false;
          };
        }
      }
    } catch {
      // Ignore storage parsing errors.
    }

    fetch(GITHUB_API_URL, { headers: { Accept: 'application/vnd.github+json' } })
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data: { stargazers_count?: unknown } | null) => {
        if (!active || !data || typeof data.stargazers_count !== 'number') return;
        const count = data.stargazers_count;
        setGithubStars(count);
        try {
          window.sessionStorage.setItem(
            STARS_CACHE_KEY,
            JSON.stringify({ stars: count, ts: Date.now() })
          );
        } catch {
          // Ignore storage quota errors.
        }
      })
      .catch(() => {
        // Silently degrade to star label if GitHub API is unreachable.
      });

    return () => {
      active = false;
    };
  }, []);

  const handleLogout = async () => {
    setSubmitting(true);
    await fetchBackend('/session', { method: 'DELETE' });
    window.dispatchEvent(new Event('studyhub:session-changed'));
    router.replace('/');
  };

  const navItems = [
    { href: '/', label: '首页' },
    { href: '/more', label: '其他' },
    { href: '/upload', label: '我要投稿' },
    { href: '/join', label: '关于我们' },
    ...(isStaff ? [{ href: '/admin', label: '管理后台' }] : []),
    { href: '/me', label: '我的' },
  ];

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <div className={styles.brandWrap} data-navbar-brand="">
          <h1 className={styles.siteHeading}>
            <Link className={styles.brandLink} href="/" prefetch={false}>
              <BrandLogo theme="light" size={28} />
              <span className={styles.brandEn}>StudyHub</span>
            </Link>
          </h1>
        </div>

        <div className={styles.rightCluster}>
          <nav className={styles.nav} aria-label="主导航">
            {navItems.map((item) => {
              const active =
                item.href === '/'
                  ? router.pathname === '/'
                  : router.pathname === item.href || router.pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={false}
                  className={`${styles.navLink} ${active ? styles.navLinkActive : ''}`}
                >
                  {item.label}
                </Link>
              );
            })}
            <a
              className={`${styles.navLink} ${styles.githubNavLink}`}
              href={GITHUB_REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`GitHub 仓库 ${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}${githubStars !== null ? `，${githubStars} Stars` : ''}`}
              title={`${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}`}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 1.27a11 11 0 0 0-3.48 21.46c.55.1.73-.24.73-.53v-1.85c-3.03.66-3.67-1.45-3.67-1.45-.5-1.26-1.21-1.6-1.21-1.6-.99-.67.07-.66.07-.66 1.09.08 1.67 1.12 1.67 1.12.97 1.66 2.54 1.18 3.16.9.1-.7.38-1.18.69-1.45-2.42-.28-4.96-1.21-4.96-5.39 0-1.19.42-2.16 1.12-2.92-.11-.28-.49-1.39.11-2.89 0 0 .92-.3 3 1.12a10.4 10.4 0 0 1 5.46 0c2.08-1.42 3-1.12 3-1.12.6 1.5.22 2.61.11 2.89.7.76 1.12 1.73 1.12 2.92 0 4.19-2.54 5.11-4.97 5.38.39.34.74 1.01.74 2.03v3.01c0 .29.19.64.74.53A11 11 0 0 0 12 1.27z" />
              </svg>
              {githubStars !== null ? (
                <span className={styles.githubStars}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <path d="M12 2.5l2.92 5.92 6.53.95-4.72 4.6 1.11 6.5L12 17.4l-5.84 3.07 1.11-6.5-4.72-4.6 6.53-.95L12 2.5z" />
                  </svg>
                  <span>{formatStarCount(githubStars)}</span>
                </span>
              ) : null}
            </a>
          </nav>

          <div className={styles.authActions}>
            {user ? (
              <div className={styles.userPill}>
                <span className={styles.userName}>{shortName}</span>
                <button
                  className={styles.logoutButton}
                  type="button"
                  onClick={handleLogout}
                  disabled={submitting}
                >
                  退出
                </button>
              </div>
            ) : (
              <>
                <span className={styles.guestPill}>游客模式</span>
                <Link className={styles.loginButton} href={loginTarget} prefetch={false}>
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
