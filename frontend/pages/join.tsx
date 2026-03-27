import { useEffect, useState } from 'react';
import { GetServerSideProps } from 'next';
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
    title: '当前状态',
    body: '资料投稿、内容阅读、校园集市与个人主页已形成四条稳定主线，当前工程重点是统一交互标准、收敛页面结构和减少跨页面体验割裂。',
  },
  {
    title: '核心技术栈',
    body: '前端采用 Next.js 14 + React + TypeScript，后端采用 Spring Boot 3 + Spring Security + MySQL，文件与图片由 OSS 体系承接，整体以“前后端分层 + 脚本化发布”保障迭代效率。',
  },
  {
    title: '迭代方向',
    body: '近期迭代围绕阅读体验、投稿效率、内容推荐与性能体感展开，优先处理高频路径卡点与交互一致性问题，不做无节制功能铺量。',
  },
  {
    title: '质量基线',
    body: '所有页面改造以“可回归、可部署、可维护”为底线：先保证稳定上线，再优化视觉细节与交互质感，避免局部优化破坏整体一致性。',
  },
];

const ENGINEERING_MODULE_CARDS = [
  {
    id: '01',
    title: '资料投稿',
    body: '持续优化分段填写路径、文件与网盘并行提交流程、预览配置与上架可用性，重点减少投稿步骤中的中断与回退。',
  },
  {
    id: '02',
    title: '学汇专栏',
    body: '承接经验、面经与题解等阅读型内容，持续拉开与资料下载页的体验差异，强化文章化结构、栏目入口与内容沉淀逻辑。',
  },
  {
    id: '03',
    title: '校园集市',
    body: '聚焦信息检索效率、卡片信息密度与交易提示规范，优化列表浏览节奏与二手信息发布体验，降低无效沟通成本。',
  },
  {
    id: '04',
    title: '个人主页',
    body: '围绕资料、购买、收益、关注关系与身份展示构建个人空间，并作为投稿默认信息来源，提高内容发布的一致性与效率。',
  },
  {
    id: '05',
    title: '推荐与 AI 能力',
    body: '逐步接入可解释推荐与结构化输出约束，优先保证合规、证据引用与稳定性，再推进更深入的个性化优化。',
  },
];

const ENGINEERING_STACK_OVERVIEW = [
  '前端基于 Next.js 页面体系与 React 组件化开发，采用 SSR 与客户端交互结合的方式平衡首屏速度、交互响应与页面可维护性。',
  '样式系统以全站统一变量与模块化样式为基础，围绕“同语义同表现”持续收敛视觉规范，避免页面级风格漂移。',
  '后端由 Spring Boot API 提供业务服务，Spring Security + JWT 负责登录态和权限边界，支撑资料、专栏、集市、求购与个人中心等模块。',
  '数据层以 MySQL 管理用户、内容、订单与互动数据，配合版本化迁移保证表结构演进可控，便于后续推荐与统计能力扩展。',
  '资源层通过 OSS 承接文件与图片，并在前端落实按需加载、懒加载与静态资源优化，提升弱网环境下的可用性与加载稳定性。',
  '发布层使用脚本化构建与服务重启流程，保证线上更新可追溯、可回退，降低频繁页面迭代带来的运维风险。',
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
                      <img
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
                    <span>当前阶段：2026 Q1</span>
                    <span>关键词：资料共享 / 内容阅读 / 校园互助</span>
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
                    <h3 className="join-engineering-subtitle">当前主要模块</h3>
                    <div className="join-engineering-module-grid">
                      {ENGINEERING_MODULE_CARDS.map((item) => (
                        <article key={item.id} className="join-engineering-module-item">
                          <span className="join-engineering-module-item__id">{item.id}</span>
                          <h4>{item.title}</h4>
                          <p className="help-text">{item.body}</p>
                        </article>
                      ))}
                    </div>
                  </section>

                  <section className="join-engineering-subsection">
                    <h3 className="join-engineering-subtitle">技术栈概述</h3>
                    <div className="join-engineering-stack-list">
                      {ENGINEERING_STACK_OVERVIEW.map((item, index) => (
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
