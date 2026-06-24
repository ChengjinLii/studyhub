import Link from 'next/link';
import { useRouter } from 'next/router';

type TabKey = 'home' | 'materials' | 'requests' | 'upload' | 'me';

interface TabItem {
  key: TabKey;
  label: string;
  href: string;
  active: (pathname: string) => boolean;
  iconPath: string;
}

const TABS: TabItem[] = [
  {
    key: 'home',
    label: '首页',
    href: '/',
    active: (pathname) => pathname === '/',
    iconPath: 'M4 11.5 12 5l8 6.5V20a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1v-8.5Z',
  },
  {
    key: 'materials',
    label: '资料',
    href: '/materials',
    active: (pathname) => pathname.startsWith('/materials'),
    iconPath: 'M6 4h9l3 3v13H6V4Zm8 0v4h4M9 12h6M9 16h6',
  },
  {
    key: 'upload',
    label: '投稿',
    href: '/upload',
    active: (pathname) => pathname === '/upload',
    iconPath: 'M12 5v10M8 9l4-4 4 4M5 19h14',
  },
  {
    key: 'requests',
    label: '求购',
    href: '/requests',
    active: (pathname) => pathname.startsWith('/requests'),
    iconPath: 'M5 6h14v11H8l-3 3V6Zm4 4h6M9 14h4',
  },
  {
    key: 'me',
    label: '我的',
    href: '/me',
    active: (pathname) => pathname === '/me' || pathname.startsWith('/u/'),
    iconPath: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 14 0',
  },
];

export default function BottomTabBar() {
  const router = useRouter();
  const pathname = router.pathname || '/';

  return (
    <nav className="mobile-bottom-nav" aria-label="移动端底部导航">
      {TABS.map((item) => {
        const isActive = item.active(pathname);
        return (
          <Link
            key={item.key}
            className={`mobile-bottom-nav__item mobile-bottom-nav__item--${item.key}${isActive ? ' is-active' : ''}`}
            href={item.href}
            aria-current={isActive ? 'page' : undefined}
            prefetch={false}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d={item.iconPath} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
