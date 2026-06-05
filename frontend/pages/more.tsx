import { GetServerSideProps } from 'next';
import Link from 'next/link';
import NavBar from '../components/NavBar';
import { readSession } from '../lib/auth';
import { SessionUser } from '../types/user';

interface MorePageProps {
  user: SessionUser | null;
}

const MORE_ENTRIES = [
  {
    href: '/column',
    label: '学汇专栏',
    eyebrow: 'Content',
    title: '经验分享与内容专栏',
    body: '浏览经验分享、课程复盘、学习路径与平台专题内容。',
    cta: '进入专栏',
  },
  {
    href: '/market',
    label: '校园集市',
    eyebrow: 'Market',
    title: '校园二手与求购',
    body: '查看同校同学发布的闲置、教材、电子设备和日常交易信息。',
    cta: '进入集市',
  },
];

export default function MorePage({ user }: MorePageProps) {
  return (
    <>
      <NavBar user={user} />
      <main className="container more-page">
        <section className="card more-hero">
          <span className="more-hero__eyebrow">Developing Area</span>
          <h1>其他功能</h1>
          <p>
            一些仍在持续完善的扩展功能收纳在这里，主导航先保持轻量，常用学习资料与投稿路径仍放在一级入口。
          </p>
        </section>

        <section className="more-entry-grid" aria-label="其他功能入口">
          {MORE_ENTRIES.map((entry) => (
            <Link key={entry.href} className="card more-entry-card" href={entry.href}>
              <span className="more-entry-card__eyebrow">{entry.eyebrow}</span>
              <div className="more-entry-card__main">
                <h2>{entry.label}</h2>
                <strong>{entry.title}</strong>
                <p>{entry.body}</p>
              </div>
              <span className="more-entry-card__cta">{entry.cta}</span>
            </Link>
          ))}
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<MorePageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  return { props: { user: session.user } };
};
