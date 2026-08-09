import { GetServerSideProps } from 'next';
import Link from 'next/link';
import NavBar from '../components/NavBar';
import { readSession } from '../lib/auth';
import { SessionUser } from '../types/user';

interface MorePageProps {
  user: SessionUser | null;
}

interface MoreEntry {
  href: string;
  label: string;
  eyebrow: string;
  title: string;
  body: string;
  cta: string;
  marker: string;
  tone: 'blue' | 'green' | 'navy' | 'violet' | 'amber';
  external?: boolean;
}

const FEATURED_ENTRIES: MoreEntry[] = [
  {
    href: '/column',
    label: '学汇专栏',
    eyebrow: 'Content',
    title: '经验分享与内容专栏',
    body: '浏览课程复盘、学习路径、经验分享与平台专题。',
    cta: '进入专栏',
    marker: '专',
    tone: 'blue',
  },
  {
    href: '/market',
    label: '校园集市',
    eyebrow: 'Market',
    title: '校园二手与求购',
    body: '查看同校同学发布的闲置、教材、电子设备与交易信息。',
    cta: '进入集市',
    marker: '市',
    tone: 'green',
  },
];

const DIRECTORY_ENTRIES: MoreEntry[] = [
  {
    href: '/join',
    label: '关于我们',
    eyebrow: 'About',
    title: '平台定位与联系方式',
    body: '了解 StudyHub、官方渠道与核心贡献者。',
    cta: '查看说明',
    marker: '介',
    tone: 'navy',
  },
  {
    href: '/join#engineering',
    label: '工程日志',
    eyebrow: 'Engineering',
    title: '技术栈与开源进展',
    body: '查看项目结构、核心技术与工程建设记录。',
    cta: '查看日志',
    marker: '工',
    tone: 'violet',
  },
  {
    href: '/identity-info',
    label: '协议与隐私',
    eyebrow: 'Policy',
    title: '用户协议与身份信息说明',
    body: '查看投稿、收益、实名与隐私相关说明。',
    cta: '查看政策',
    marker: '规',
    tone: 'amber',
  },
  {
    href: 'mailto:chengjinli@std.uestc.edu.cn',
    label: '联系邮箱',
    eyebrow: 'Support',
    title: '问题反馈与内容协作',
    body: '反馈资料、账号、支付或内容审核问题。',
    cta: '发送邮件',
    marker: '@',
    tone: 'blue',
    external: true,
  },
  {
    href: 'https://github.com/ChengjinLii/studyhub',
    label: 'GitHub',
    eyebrow: 'Open Source',
    title: 'StudyHub 开源仓库',
    body: '关注代码更新、提交 issue 或参与项目协作。',
    cta: '打开仓库',
    marker: 'GH',
    tone: 'navy',
    external: true,
  },
];

function MoreEntryLink({ entry, featured = false }: { entry: MoreEntry; featured?: boolean }) {
  const className = featured ? 'more-feature-card' : 'more-directory-row';
  const content = (
    <>
      <span className="more-entry-marker" aria-hidden="true">
        {entry.marker}
      </span>
      <span className="more-entry-copy">
        <span className="more-entry-kicker">{entry.eyebrow}</span>
        {featured ? <h2>{entry.label}</h2> : <h3>{entry.label}</h3>}
        <strong>{entry.title}</strong>
        <span className="more-entry-description">{entry.body}</span>
      </span>
      <span className="more-entry-action">
        {entry.cta}
        <span aria-hidden="true">{entry.external ? '↗' : '→'}</span>
      </span>
    </>
  );

  if (entry.external) {
    return (
      <a
        className={className}
        data-tone={entry.tone}
        href={entry.href}
        target={entry.href.startsWith('http') ? '_blank' : undefined}
        rel={entry.href.startsWith('http') ? 'noopener noreferrer' : undefined}
      >
        {content}
      </a>
    );
  }

  return (
    <Link className={className} data-tone={entry.tone} href={entry.href}>
      {content}
    </Link>
  );
}

export default function MorePage({ user }: MorePageProps) {
  return (
    <>
      <NavBar user={user} />
      <main className="container more-page">
        <header className="more-hero">
          <div className="more-hero__accent" aria-hidden="true">
            <span />
            <span />
          </div>
          <span className="more-hero__eyebrow">StudyHub Directory</span>
          <h1>其他功能</h1>
          <p>内容、校园服务、平台说明与帮助入口集中在这里。</p>
        </header>

        <section className="more-section" aria-labelledby="more-explore-title">
          <div className="more-section-heading">
            <div>
              <span className="more-section-heading__eyebrow">Explore</span>
              <h2 id="more-explore-title">浏览与交流</h2>
            </div>
            <p>发现校园内容与同校交易信息</p>
          </div>
          <div className="more-feature-grid">
            {FEATURED_ENTRIES.map((entry) => (
              <MoreEntryLink key={entry.href} entry={entry} featured />
            ))}
          </div>
        </section>

        <section className="more-section" aria-labelledby="more-platform-title">
          <div className="more-section-heading">
            <div>
              <span className="more-section-heading__eyebrow">Platform</span>
              <h2 id="more-platform-title">平台与支持</h2>
            </div>
            <p>了解项目，获取帮助或参与协作</p>
          </div>
          <div className="more-directory">
            {DIRECTORY_ENTRIES.map((entry) => (
              <MoreEntryLink key={entry.href} entry={entry} />
            ))}
          </div>
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<MorePageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  return { props: { user: session.user } };
};
