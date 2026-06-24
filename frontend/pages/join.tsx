import { useEffect, useState } from 'react';
import { GetServerSideProps } from 'next';
import { useAppDialog } from '../components/AppDialogProvider';
import AppImage from '../components/AppImage';
import NavBar from '../components/NavBar';
import { readSession } from '../lib/auth';
import { SessionUser } from '../types/user';

const COMMUNITY_QQ = '245934740';
const CONTACT_EMAIL = 'chengjinli@std.uestc.edu.cn';
const CORE_CONTRIBUTORS = '李承锦、曾逸帆';

const JOIN_TRUST_ITEMS = [
  { label: '平台定位', value: '校园资料与学习互助' },
  { label: '官方 QQ 群', value: COMMUNITY_QQ },
  { label: '开源仓库', value: 'ChengjinLii/studyhub' },
  { label: '内容版权', value: '归原作者所有' },
];

const ABOUT_POINTS = [
  {
    title: '平台定位',
    body: 'StudyHub 聚焦校园学习场景，核心目标是把“资料共享、专栏阅读、校园互助、个人主页”放在同一条稳定体验链路中，让同学在一个站内完成找资料、看内容、发布与互动。',
  },
  {
    title: '当前状态',
    body: '当前阶段已经完成主站信息架构收敛，重点放在页面层级统一、投稿链路可用性、阅读体验连续性与移动端适配稳定性，同时持续压缩操作路径与无效点击。',
  },
  {
    title: '公开内容',
    body: '对外公开渠道集中在官方群、微信公众号与站内工程日志，便于查看功能迭代方向、页面更新节奏和使用说明；涉安全策略、密钥与内部运维细节不在公开范围。',
  },
  {
    title: '长期方向',
    body: '后续将围绕“内容质量提升、推荐能力增强、创作者体系完善、站点性能优化”持续迭代，在不牺牲稳定性的前提下提升学习效率与内容沉淀价值。',
  },
];

const ENGINEERING_STATUS_CARDS = [
  {
    title: '产品主线',
    body: 'StudyHub 面向高校学习资料共享和校园互助场景，主线能力包括资料发布与检索、经验内容、求购协作、创作者结算、校园集市和个人主页。',
  },
  {
    title: '前端技术栈',
    body: '前端使用 Next.js 14、React、TypeScript 与 Playwright/Vitest 组织页面渲染、组件交互、关键路径测试和单元测试。',
  },
  {
    title: '后端技术栈',
    body: '后端使用 FastAPI、SQLAlchemy、Pydantic Settings、Uvicorn、pytest 与 Alembic，围绕认证、资料、支付、结算、MCP 和 AI Agent 提供 API 能力。',
  },
  {
    title: '运行与存储',
    body: '生产侧以 MySQL、OSS、systemd、Nginx、worker 与脚本化预检为核心，日志、健康检查和 Prometheus 指标用于支撑排障与稳定性观察。',
  },
];

const ENGINEERING_STRUCTURE_CARDS = [
  {
    id: '01',
    title: 'backend/',
    body: 'FastAPI 后端、测试、fixtures 与运维辅助代码都放在这里，是主要的业务逻辑与服务入口。',
  },
  {
    id: '02',
    title: 'frontend/',
    body: 'Next.js 前端工程，负责首页、资料页、校园集市、个人主页与内容展示等交互体验。',
  },
  {
    id: '03',
    title: 'reports/',
    body: '公开的技术报告、项目复盘材料与对外说明，适合协作者快速理解项目背景与设计取舍。',
  },
  {
    id: '04',
    title: 'scripts/',
    body: '开发、部署、worker 与数据库操作脚本集中在这里，方便本地开发和服务维护。',
  },
];

const ENGINEERING_FUTURE_ITEMS = [
  '内容系统：继续完善资料发布、预览、下载、举报和审核流程，保证用户能稳定提交和获取资料。',
  '推荐检索：围绕标签、学校学院专业、下载互动和 Agent 语义理解改进推荐与搜索体验。',
  '开放能力：通过 MCP 和公开只读能力，让外部 Agent 可以推荐平台资料链接，但不绕过站内下载和权限规则。',
  '工程质量：持续收紧类型检查、关键路径测试、日志观测、部署预检和安全基线，降低线上回归风险。',
];

interface JoinPageProps {
  user: SessionUser | null;
}

export default function JoinPage({ user }: JoinPageProps) {
  const dialog = useAppDialog();
  const [copied, setCopied] = useState(false);
  const [emailCopied, setEmailCopied] = useState(false);
  const [activeSection, setActiveSection] = useState('overview');

  const copyText = async (text: string, onDone: () => void) => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        onDone();
        return;
      }
    } catch {
      // ignore
    }
    await dialog.alert({
      title: '手动复制',
      message: `请手动复制以下内容：\n${text}`,
    });
  };

  const handleCopyQq = async () => {
    await copyText(COMMUNITY_QQ, () => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleCopyEmail = async () => {
    await copyText(CONTACT_EMAIL, () => {
      setEmailCopied(true);
      setTimeout(() => setEmailCopied(false), 2000);
    });
  };

  useEffect(() => {
    const sections = ['overview', 'contact', 'channels', 'engineering', 'summary']
      .map((id) => document.getElementById(id))
      .filter((node): node is HTMLElement => Boolean(node));
    if (!sections.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible?.target?.id) setActiveSection(visible.target.id);
      },
      { rootMargin: '-20% 0px -60% 0px', threshold: [0.2, 0.45, 0.7] }
    );

    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const navItems = [
    { id: 'overview', label: '关于 StudyHub' },
    { id: 'contact', label: '联系方式' },
    { id: 'channels', label: '官方公众号' },
    { id: 'engineering', label: '工程日志' },
    { id: 'summary', label: '平台概览' },
  ];

  return (
    <>
      <NavBar user={user} />
      <main className="container join-page">
        <div className="join-layout">
          <aside className="me-sidebar join-sidebar">
            <div className="me-sidebar__brand">关于我们</div>
            <div className="me-sidebar__group">
              <div className="me-sidebar__label">页面导航</div>
              <div className="me-sidebar__items">
                {navItems.map((item) => (
                  <a
                    key={item.id}
                    className={`me-sidebar__item ${activeSection === item.id ? 'active' : ''}`}
                    href={`#${item.id}`}
                    onClick={() => setActiveSection(item.id)}
                  >
                    <span className="me-sidebar__indicator" aria-hidden="true" />
                    <span className="me-sidebar__text">{item.label}</span>
                  </a>
                ))}
              </div>
            </div>
          </aside>

          <div className="join-main">
            <section className="join-section-block join-section-block--overview" id="overview">
              <section className="card me-hero join-hero-card">
                <div className="me-hero__eyebrow">About StudyHub</div>
                <h1 className="me-hero__title">关于 StudyHub</h1>
                <div className="join-hero-card__divider" />
                <div className="me-hero__meta join-hero-card__meta">
                  <span>
                    <strong>核心贡献者：</strong>
                    {CORE_CONTRIBUTORS}
                  </span>
                </div>
                <div className="join-trust-grid" aria-label="平台信息概览">
                  {JOIN_TRUST_ITEMS.map((item) => (
                    <div key={item.label} className="join-trust-item">
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                    </div>
                  ))}
                </div>
              </section>
            </section>

            <section className="join-section-block join-section-block--contact" id="contact">
              <div className="card join-panel-card">
                <div className="join-section-head join-panel-head">
                  <span className="join-section-head__eyebrow">Contact</span>
                  <h2>联系方式</h2>
                </div>
                <div className="join-contact-strip">
                  <div className="join-info-row join-info-row--action">
                    <div className="join-info-row__body">
                      <span className="join-info-row__label">官方 QQ 群</span>
                      <strong className="join-info-row__value">{COMMUNITY_QQ}</strong>
                    </div>
                    <button className="button join-inline-action" type="button" onClick={handleCopyQq}>
                      {copied ? '已复制' : '复制官方群号'}
                    </button>
                  </div>

                  <div className="join-info-row join-info-row--action">
                    <div className="join-info-row__body">
                      <span className="join-info-row__label">联系邮箱</span>
                      <a className="join-info-row__value join-info-row__value--link" href={`mailto:${CONTACT_EMAIL}`}>
                        {CONTACT_EMAIL}
                      </a>
                    </div>
                    <button className="button join-inline-action join-inline-action--soft" type="button" onClick={handleCopyEmail}>
                      {emailCopied ? '已复制' : '复制邮箱'}
                    </button>
                  </div>
                </div>
              </div>
            </section>

            <section className="join-section-block" id="channels">
              <div className="card join-panel-card">
                <div className="join-section-head join-panel-head">
                  <span className="join-section-head__eyebrow">Official Channel</span>
                  <h2>官方渠道</h2>
                </div>
                <div className="join-channel-layout" aria-label="官方微信公众号">
                  <div className="join-channel-panel__copy">
                    <p className="join-panel__lead">关注公众号可获取公告、功能更新与运营动态。</p>
                  </div>
                  <div className="wechat-card__qr join-channel-layout__visual">
                    <div className="lazy-image-box join-qr-box">
                      <AppImage
                        className="lazy-blur"
                        src="/wechat/wechat-qr.jpeg"
                        alt="StudyHub 官方微信公众号二维码"
                        loading="lazy"
                        decoding="async"
                        onLoad={(event) => event.currentTarget.classList.add('is-loaded')}
                      />
                    </div>
                    <span className="wechat-card__hint">微信扫码关注</span>
                  </div>
                </div>
              </div>
            </section>

            <section className="join-section-block" id="engineering">
              <div className="card join-panel-card">
                <div className="join-section-head join-panel-head">
                  <span className="join-section-head__eyebrow">Engineering Blog</span>
                  <h2>工程日志</h2>
                </div>
                <div className="join-engineering-block">
                  <div className="join-engineering-meta">
                    <span>当前仓库：studyhub</span>
                    <span>公开主线：FastAPI + Next.js</span>
                    <span>官网：https://study-hub.cn</span>
                  </div>
                  <div className="join-engineering-links" aria-label="GitHub 索引">
                    <a
                      className="join-engineering-link"
                      href="https://github.com/ChengjinLii/studyhub"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      GitHub 主仓库
                    </a>
                    <a
                      className="join-engineering-link"
                      href="https://github.com/ChengjinLii/studyhub-springboot"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      SpringBoot 版本
                    </a>
                  </div>

                  <div className="join-engineering-status-grid">
                    {ENGINEERING_STATUS_CARDS.map((item) => (
                      <article key={item.title} className="join-engineering-status-item">
                        <h3>{item.title}</h3>
                        <p className="help-text">{item.body}</p>
                      </article>
                    ))}
                  </div>

                  <section className="join-engineering-subsection">
                    <h3 className="join-engineering-subtitle">仓库结构</h3>
                    <div className="join-engineering-module-grid">
                      {ENGINEERING_STRUCTURE_CARDS.map((item) => (
                        <article key={item.id} className="join-engineering-module-item">
                          <span className="join-engineering-module-item__id">{item.id}</span>
                          <h4>{item.title}</h4>
                          <p className="help-text">{item.body}</p>
                        </article>
                      ))}
                    </div>
                  </section>

                  <section className="join-engineering-subsection">
                    <h3 className="join-engineering-subtitle">未来规划</h3>
                    <div className="join-engineering-stack-list">
                      {ENGINEERING_FUTURE_ITEMS.map((item, index) => (
                        <article key={item} className="join-engineering-stack-item">
                          <span className="join-engineering-stack-item__id">{String(index + 1).padStart(2, '0')}</span>
                          <p className="help-text">{item}</p>
                        </article>
                      ))}
                    </div>
                  </section>
                </div>
              </div>
            </section>

            <section className="join-section-block" id="summary">
              <div className="card join-panel-card">
                <div className="join-section-head join-panel-head">
                  <span className="join-section-head__eyebrow">Overview</span>
                  <h2>平台概览</h2>
                </div>
                <div className="join-summary-list">
                  {ABOUT_POINTS.map((item, index) => (
                    <article key={item.title} className="join-summary-item">
                      <span className="join-summary-item__index">{String(index + 1).padStart(2, '0')}</span>
                      <div className="join-summary-item__body">
                        <h3>{item.title}</h3>
                        <p className="help-text">{item.body}</p>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </section>
          </div>
        </div>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<JoinPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  return { props: { user: session.user } };
};
