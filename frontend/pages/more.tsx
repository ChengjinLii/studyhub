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
  {
    href: '/join',
    label: '关于我们',
    eyebrow: 'About',
    title: '平台定位与联系方式',
    body: '了解 StudyHub 的平台说明、联系方式、官方渠道与核心贡献者。',
    cta: '查看说明',
  },
  {
    href: '/join#engineering',
    label: '工程日志',
    eyebrow: 'Engineering',
    title: '开源仓库与迭代计划',
    body: '查看项目结构、技术栈、公开仓库和后续工程规划。',
    cta: '查看日志',
  },
  {
    href: '/identity-info',
    label: '协议与隐私',
    eyebrow: 'Policy',
    title: '用户协议与身份信息说明',
    body: '查看平台在投稿、收益、实名与隐私方面的说明。',
    cta: '查看政策',
  },
  {
    href: 'mailto:chengjinli@std.uestc.edu.cn',
    label: '联系邮箱',
    eyebrow: 'Support',
    title: '反馈问题与内容协作',
    body: '遇到资料、账号、支付或内容审核问题时，可通过邮箱联系维护者。',
    cta: '发送邮件',
    external: true,
  },
  {
    href: 'https://github.com/ChengjinLii/studyhub',
    label: 'GitHub',
    eyebrow: 'Open Source',
    title: '查看 StudyHub 开源仓库',
    body: '关注代码更新、提交 issue 或查看当前项目实现。',
    cta: '打开仓库',
    external: true,
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
            扩展功能、平台说明和帮助入口收纳在这里。主导航保持轻量，常用的资料检索、求购和投稿仍放在一级入口。
          </p>
        </section>

        <section className="more-entry-grid" aria-label="其他功能入口">
          {MORE_ENTRIES.map((entry) => (
            entry.external ? (
              <a
                key={entry.href}
                className="card more-entry-card"
                href={entry.href}
                target={entry.href.startsWith('http') ? '_blank' : undefined}
                rel={entry.href.startsWith('http') ? 'noopener noreferrer' : undefined}
              >
                <span className="more-entry-card__eyebrow">{entry.eyebrow}</span>
                <div className="more-entry-card__main">
                  <h2>{entry.label}</h2>
                  <strong>{entry.title}</strong>
                  <p>{entry.body}</p>
                </div>
                <span className="more-entry-card__cta">{entry.cta}</span>
              </a>
            ) : (
              <Link key={entry.href} className="card more-entry-card" href={entry.href}>
                <span className="more-entry-card__eyebrow">{entry.eyebrow}</span>
                <div className="more-entry-card__main">
                  <h2>{entry.label}</h2>
                  <strong>{entry.title}</strong>
                  <p>{entry.body}</p>
                </div>
                <span className="more-entry-card__cta">{entry.cta}</span>
              </Link>
            )
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
