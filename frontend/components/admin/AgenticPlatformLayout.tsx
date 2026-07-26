import Link from 'next/link';
import { ReactNode } from 'react';
import NavBar from '../NavBar';
import { SessionUser } from '../../types/user';

type AgenticPlatformSection = 'runs' | 'research' | 'artifacts';

interface AgenticPlatformLayoutProps {
  user: SessionUser;
  active: AgenticPlatformSection;
  children: ReactNode;
}

const navItems: Array<{ key: AgenticPlatformSection; href: string; label: string }> = [
  { key: 'runs', href: '/admin/agentic-platform', label: '运行控制台' },
  { key: 'research', href: '/admin/agentic-platform/research', label: 'DeepResearch' },
  { key: 'artifacts', href: '/admin/agentic-platform/artifacts', label: 'Artifacts' },
];

export default function AgenticPlatformLayout({ user, active, children }: AgenticPlatformLayoutProps) {
  return (
    <>
      <NavBar user={user} />
      <main className="container agentic-platform">
        <header className="agentic-platform__hero">
          <div>
            <span className="agentic-platform__eyebrow">ADMIN · AGENTIC CONTROL PLANE</span>
            <h1>Agent 运行控制台</h1>
            <p>可观察、可中断的 Shadow Mode 控制面。仅展示结构化运行信号，不展示私有推理过程。</p>
          </div>
          <Link className="button ghost small" href="/admin">
            返回管理后台
          </Link>
        </header>
        <nav className="agentic-platform__nav" aria-label="Agentic 平台导航">
          {navItems.map((item) => (
            <Link
              className={`agentic-platform__nav-link ${active === item.key ? 'is-active' : ''}`}
              href={item.href}
              key={item.key}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        {children}
      </main>
    </>
  );
}
