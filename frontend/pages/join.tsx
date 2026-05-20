import { useEffect, useState } from 'react';
import { GetServerSideProps } from 'next';
import AppImage from '../components/AppImage';
import NavBar from '../components/NavBar';
import { readSession } from '../lib/auth';
import { SessionUser } from '../types/user';

const COMMUNITY_QQ = '245934740';
const CONTACT_EMAIL = 'chengjinli@std.uestc.edu.cn';
const CORE_CONTRIBUTORS = '李承锦、曾逸帆';

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
    title: '仓库定位',
    body: 'StudyHub 是一个面向高校场景的知识共享与校园互助平台，提供资料共享、经验分享、求购协作与校园集市等功能，官网为 https://study-hub.cn。',
  },
  {
    title: '核心功能',
    body: '当前主线能力集中在资料共享、经验分享、求购协作与校园集市四块，目标是在一个站内完成找资料、看内容、发布与互动。',
  },
  {
    title: '技术栈',
    body: '后端基于 FastAPI、SQLAlchemy、Pydantic Settings 与 Uvicorn，前端基于 Next.js 14、React 与 TypeScript，并围绕 MySQL、OSS、Redis、worker 与脚本化部署组织工程。',
  },
  {
    title: '相关项目',
    body: '初版 SpringBoot 实现仍保留为相关项目；当前仓库聚焦 FastAPI 主线，并持续把开发、预览与生产环境说明收敛为适合开源协作的形式。',
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
  '资料审核：逐步完善资料审核、版权风险识别与异常内容处理流程，提升平台内容质量与合规性。',
  '语义搜索：为资料、经验分享和求购内容提供更自然的检索体验，减少关键词命中不足的问题。',
  'MCP 接口：开放面向智能体和开发工具的标准化能力入口，便于后续接入更丰富的自动化工作流。',
  '检索与推荐：继续增强资料推荐、贡献榜与校园集市的排序策略，让首页内容更贴近用户当前需求。',
];

interface JoinPageProps {
  user: SessionUser | null;
}

export default function JoinPage({ user }: JoinPageProps) {
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
    window.prompt('请使用 Ctrl+C 复制内容', text);
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
    const sections = ['overview', 'channels', 'engineering', 'summary']
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
