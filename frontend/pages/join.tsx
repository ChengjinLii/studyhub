import { useEffect, useState } from 'react';
import { GetServerSideProps } from 'next';
import { useAppDialog } from '../components/AppDialogProvider';
import AppImage from '../components/AppImage';
import NavBar from '../components/NavBar';
import UserGrowthChart from '../components/join/UserGrowthChart';
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
    title: '产品与服务边界',
    body: 'StudyHub 围绕高校学习资料和校园互助组织产品能力，覆盖资料投稿、检索与预览、下载与支付、经验内容、求购协作、校园集市、个人主页和创作者结算。各条业务链路共享统一的账户、权限、内容状态和错误响应约定，减少页面之间的行为差异。',
  },
  {
    title: '前端应用',
    body: '前端基于 Next.js 15、React 18 与 TypeScript 构建，结合服务端渲染和客户端交互承载首页、资料详情、投稿、个人主页和管理端等页面。Vitest 负责组件与工具函数回归，Playwright 同时验证开发模式和生产构建下的登录、检索、投稿等关键路径。',
  },
  {
    title: '后端与 API',
    body: '后端以 FastAPI、SQLAlchemy、Pydantic Settings 和 Uvicorn 为基础，按 routes、services、repos、models 分层组织认证、资料、评论、求购、支付、结算与通知逻辑。公开接口采用统一响应结构和 RESTful 资源语义，历史接口保留必要兼容，避免前后端升级造成使用中断。',
  },
  {
    title: '数据与文件',
    body: '业务数据在生产环境使用 MySQL，本地开发可使用 SQLite；资料文件由阿里云 OSS 承载，应用只向通过登录、订单和权限校验的用户签发短时访问地址。Redis 用于需要跨进程一致性的锁与运行态能力，数据库迁移、备份和恢复验证由独立脚本管理。',
  },
  {
    title: '支付与创作者结算',
    body: '付费资料通过支付宝网页支付完成订单确认，回调验签、幂等处理和订单状态更新均在后端执行。创作者结算记录与实际转账绑定，失败转账会释放仍待结算的记录，避免出现资金已记账但未实际支付，或同一笔结算被重复处理。',
  },
  {
    title: '检索实验与 MCP',
    body: '检索实验以独立工程维护关键词、向量、混合召回、重排和权限泄漏评测，不与在线业务代码耦合。远程 MCP 继续提供受治理的只读资料搜索、详情、推荐和平台规则工具，只返回公开元数据与站内链接，不直接暴露受保护文件或绕过登录、付费和下载规则。站内 Agent 正在基于原生 Hermes 重新建设，尚不作为现有产品能力对外承诺。',
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
    title: 'studyhub-agent/',
    body: '保留独立 RAG 检索实验，并作为 Agent V2 的重建区域；实验代码与在线业务服务保持边界，便于单独验证召回、排序和权限约束。',
  },
  {
    id: '04',
    title: 'scripts/',
    body: '开发启动、生产预检、部署冒烟、worker、依赖更新、安全检查和数据库管理脚本集中在这里。',
  },
  {
    id: '05',
    title: 'reports/',
    body: '公开技术报告、覆盖率结果与项目复盘材料，记录架构边界、验证结果和重要设计取舍。',
  },
  {
    id: '06',
    title: '.github/',
    body: '持续集成和依赖更新配置，负责前后端检查、迁移验证、敏感文件防护与生产构建门禁。',
  },
];

const ENGINEERING_FLOW_ITEMS = [
  {
    title: '资料投稿与交付',
    body: '前端先完成必填项、交付方式和文件状态校验，再向后端提交幂等投稿请求；后端负责资料元数据、站内文件或网盘信息的持久化。资料详情页根据交付方式、价格和当前用户权限展示预览、领取、购买或下载入口。',
  },
  {
    title: '检索与推荐',
    body: '搜索会统一处理多关键词、课程、标签、学校、学院和专业等条件，再结合时间、下载量和相关性返回结果。推荐能力复用公开可见资料元数据，避免将不可见、已下架或无法交付的内容推给用户。',
  },
  {
    title: '订单与结算',
    body: '创建订单、拉起支付宝、异步回调、支付结果确认和下载授权形成完整闭环；涉及创作者收入时，结算单会绑定到具体转账，并通过幂等状态机处理成功、失败与重复回调。',
  },
  {
    title: 'MCP 外部接入',
    body: '外部客户端通过 MCP 的 initialize、tools/list 和 tools/call 发现资料检索能力，只能获得结构化推荐结果和 StudyHub 页面链接。站内登录、付费、下载权限和配额仍由业务后端独立校验。',
  },
];

const ENGINEERING_GUARDRAIL_ITEMS = [
  {
    title: '代码质量',
    body: '前端执行 TypeScript、ESLint、Vitest 与 Playwright，后端执行 Ruff、pytest 和覆盖率统计；代码体积、Shell 语法与敏感文件另有独立检查。',
  },
  {
    title: '数据库安全',
    body: '生产发布先执行只读结构预检，迁移默认不会被部署脚本静默执行；需要变更时先生成计划并备份，再经过 MySQL 升降级和恢复验证。',
  },
  {
    title: '发布验证',
    body: '前端以生产模式完成构建后再启动服务，发布脚本检查构建完整性、后端健康与就绪状态、公开资料接口、主要页面和安全响应头。',
  },
  {
    title: '安全边界',
    body: '认证、支付签名、下载授权、可信主机与代理、请求限流、Markdown 和支付表单处理均有服务端约束；公开日志和页面不展示密钥、内部路径或受保护资源地址。',
  },
  {
    title: '运行观测',
    body: '结构化日志携带请求标识，健康检查区分进程存活与依赖就绪，Prometheus 指标覆盖 HTTP、MCP 和 worker 的调用量、错误与耗时。',
  },
];

const ENGINEERING_FUTURE_ITEMS = [
  '内容治理：继续完善文件安全检查、版权举报、资料状态追踪和异常交付处理，使投稿、审核、预览与下载形成可追溯闭环。',
  '检索推荐：在现有多关键词和字段过滤基础上，逐步评估关键词召回、语义召回、重排和离线评测，优先提升课程名、年份与资料类型的准确命中。',
  'Agent V2：先验证原生 Hermes 的对话、工具调用和记忆能力，再逐层接入 StudyHub RAG、联网搜索、群体记忆与训练闭环；每层均保持可独立测试和回退。',
  '开放接入：完善 MCP 对外说明、OAuth 用户授权、调用配额和审计能力，确保外部客户端能推荐资料，但不能代替用户绕过站内权益流程。',
  '工程保障：逐步扩大严格类型检查、契约测试和生产模式端到端覆盖，并持续完善依赖升级、备份恢复、运行告警与安全基线。',
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
    const sections = ['overview', 'growth', 'contact', 'channels', 'engineering', 'summary']
      .map((id) => document.getElementById(id))
      .filter((node): node is HTMLElement => Boolean(node));
    if (!sections.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible?.target?.id) setActiveSection(visible.target.id);
      },
      { rootMargin: '-20% 0px -60% 0px', threshold: [0.2, 0.45, 0.7] }
    );

    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const navItems = [
    { id: 'overview', label: '关于 StudyHub' },
    { id: 'growth', label: '用户增长' },
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

            <section className="join-section-block" id="growth">
              <div className="card join-panel-card join-growth-card">
                <div className="join-section-head join-panel-head">
                  <span className="join-section-head__eyebrow">Community Growth</span>
                  <h2>用户增长</h2>
                </div>
                <UserGrowthChart />
              </div>
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
                  <p className="join-engineering-intro">
                    工程日志记录 StudyHub
                    当前公开主线的系统组成、关键业务链路和质量保障方式。这里侧重说明代码如何组织、功能如何协作以及发布如何验证，不公开生产密钥、内部地址和安全策略细节。
                  </p>
                  <div className="join-engineering-meta">
                    <span>应用架构：Next.js + FastAPI</span>
                    <span>数据与文件：MySQL + Redis + OSS</span>
                    <span>运行环境：Node.js 22 + Python 3.12</span>
                    <span>公开协议：RESTful API + MCP</span>
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
                    <h3 className="join-engineering-subtitle">关键业务链路</h3>
                    <div className="join-engineering-stack-list">
                      {ENGINEERING_FLOW_ITEMS.map((item, index) => (
                        <article key={item.title} className="join-engineering-stack-item">
                          <span className="join-engineering-stack-item__id">{String(index + 1).padStart(2, '0')}</span>
                          <div className="join-engineering-stack-item__body">
                            <h4>{item.title}</h4>
                            <p className="help-text">{item.body}</p>
                          </div>
                        </article>
                      ))}
                    </div>
                  </section>

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
                    <h3 className="join-engineering-subtitle">质量与运行保障</h3>
                    <div className="join-engineering-stack-list">
                      {ENGINEERING_GUARDRAIL_ITEMS.map((item, index) => (
                        <article key={item.title} className="join-engineering-stack-item">
                          <span className="join-engineering-stack-item__id">{String(index + 1).padStart(2, '0')}</span>
                          <div className="join-engineering-stack-item__body">
                            <h4>{item.title}</h4>
                            <p className="help-text">{item.body}</p>
                          </div>
                        </article>
                      ))}
                    </div>
                  </section>

                  <section className="join-engineering-subsection">
                    <h3 className="join-engineering-subtitle">持续建设方向</h3>
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
