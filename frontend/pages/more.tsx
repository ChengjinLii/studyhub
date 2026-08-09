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
  description: string;
  external?: boolean;
}

interface MoreGroup {
  id: string;
  title: string;
  entries: MoreEntry[];
}

const MORE_GROUPS: MoreGroup[] = [
  {
    id: 'campus',
    title: '内容与校园',
    entries: [
      {
        href: '/column',
        label: '学汇专栏',
        description: '课程复盘、学习路径、经验分享与平台专题。',
      },
      {
        href: '/market',
        label: '校园集市',
        description: '同校闲置、教材、电子设备与求购信息。',
      },
    ],
  },
  {
    id: 'platform',
    title: '平台信息',
    entries: [
      {
        href: '/join',
        label: '关于我们',
        description: '平台定位、官方渠道与核心贡献者。',
      },
      {
        href: '/join#engineering',
        label: '工程日志',
        description: '技术栈、开源进展与工程建设记录。',
      },
      {
        href: '/identity-info',
        label: '协议与隐私',
        description: '投稿、收款码、收益结算与隐私相关说明。',
      },
    ],
  },
  {
    id: 'contact',
    title: '联系与协作',
    entries: [
      {
        href: 'mailto:chengjinli@std.uestc.edu.cn',
        label: '联系邮箱',
        description: '反馈资料、账号、支付或内容审核问题。',
        external: true,
      },
      {
        href: 'https://github.com/ChengjinLii/studyhub',
        label: 'GitHub',
        description: '查看源码、提交 issue 或参与项目协作。',
        external: true,
      },
    ],
  },
];

function MoreLink({ entry }: { entry: MoreEntry }) {
  const content = (
    <>
      <span className="more-link__copy">
        <strong>{entry.label}</strong>
        <span>{entry.description}</span>
      </span>
      <span className="more-link__arrow" aria-hidden="true">
        {entry.external ? '↗' : '→'}
      </span>
    </>
  );

  if (entry.external) {
    return (
      <a
        className="more-link"
        href={entry.href}
        target={entry.href.startsWith('http') ? '_blank' : undefined}
        rel={entry.href.startsWith('http') ? 'noopener noreferrer' : undefined}
      >
        {content}
      </a>
    );
  }

  return (
    <Link className="more-link" href={entry.href}>
      {content}
    </Link>
  );
}

export default function MorePage({ user }: MorePageProps) {
  return (
    <>
      <NavBar user={user} />
      <main className="container more-page">
        <header className="more-header">
          <div className="more-header__copy">
            <h1>其他功能</h1>
            <p>内容专栏、校园服务、平台信息与支持入口。</p>
          </div>
          <nav className="more-header__nav" aria-label="功能分类">
            {MORE_GROUPS.map((group) => (
              <a key={group.id} href={`#${group.id}`}>
                {group.title}
              </a>
            ))}
          </nav>
        </header>

        <div className="more-directory" aria-label="其他功能入口">
          {MORE_GROUPS.map((group, index) => (
            <section className="more-group" id={group.id} key={group.id} aria-labelledby={`more-${group.id}`}>
              <div className="more-group__heading">
                <span aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                <h2 id={`more-${group.id}`}>{group.title}</h2>
              </div>
              <div className="more-link-list">
                {group.entries.map((entry) => (
                  <MoreLink key={entry.href} entry={entry} />
                ))}
              </div>
            </section>
          ))}
        </div>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<MorePageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  return { props: { user: session.user } };
};
