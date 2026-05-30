import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { FormEvent, useEffect, useRef, useState } from 'react';
import NavBar from '../../components/NavBar';
import { readSession } from '../../lib/auth';
import { createMaterialRequest } from '../../lib/requestsApi';
import { toErrorMessage } from '../../lib/errors';
import { SessionUser } from '../../types/user';
import { SUPPORTED_SCHOOL, SUPPORTED_COLLEGES, SUPPORTED_MAJORS } from '../../constants/metadata';
import { REQUEST_TIERS, RequestTierValue } from '../../constants/request';

const MAX_TITLE_LENGTH = 30;
const MAX_DESC_LENGTH = 300;
const MAX_PREVIEW_REQUIREMENT_LENGTH = 200;

interface RequestNewProps {
  user: SessionUser;
}

const REQUEST_NAV_ITEMS = [
  { id: 'request-overview', label: '页面总览' },
  { id: 'request-basic', label: '基础信息' },
  { id: 'request-budget', label: '预算与期限' },
  { id: 'request-scope', label: '匹配范围' },
];

export default function RequestNewPage({ user }: RequestNewProps) {
  const [title, setTitle] = useState('');
  const [intro, setIntro] = useState('');
  const [budget, setBudget] = useState('');
  const [urgencyTier, setUrgencyTier] = useState<RequestTierValue>('FLEX');
  const [creatorFloor, setCreatorFloor] = useState('');
  const [previewRequirement, setPreviewRequirement] = useState('');
  const [school, setSchool] = useState('');
  const [college, setCollege] = useState('');
  const [major, setMajor] = useState('');
  const [status, setStatus] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [payFormHtml, setPayFormHtml] = useState('');
  const [activeSection, setActiveSection] = useState('request-overview');
  const formContainerRef = useRef<HTMLDivElement | null>(null);
  const activeTier = REQUEST_TIERS.find((item) => item.value === urgencyTier) || REQUEST_TIERS[REQUEST_TIERS.length - 1];

  useEffect(() => {
    if (!payFormHtml || !formContainerRef.current) return;
    formContainerRef.current.innerHTML = payFormHtml;
    const form = formContainerRef.current.querySelector('form') as HTMLFormElement | null;
    if (form) {
      form.submit();
    }
  }, [payFormHtml]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const sections = REQUEST_NAV_ITEMS
      .map((item) => document.getElementById(item.id))
      .filter((item): item is HTMLElement => Boolean(item));
    if (!sections.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
        if (visible.length > 0) {
          setActiveSection(visible[0].target.id);
        }
      },
      { rootMargin: '-20% 0px -60% 0px', threshold: [0.1, 0.35, 0.7] }
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const jumpToSection = (id: string) => {
    if (typeof window === 'undefined') return;
    const target = document.getElementById(id);
    if (!target) return;
    setActiveSection(id);
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus(null);
    const trimmedTitle = title.trim();
    const trimmedIntro = intro.trim();
    if (!trimmedTitle || !trimmedIntro) {
      setStatus({ type: 'error', text: '请填写标题和简介。' });
      return;
    }
    if (!school && (college || major)) {
      setStatus({ type: 'error', text: '请选择学校后再填写学院/专业。' });
      return;
    }
    if (!college && major) {
      setStatus({ type: 'error', text: '请选择学院后再填写专业。' });
      return;
    }
    const budgetValue = budget ? Number(budget) : NaN;
    const tierConfig = REQUEST_TIERS.find((item) => item.value === urgencyTier) || REQUEST_TIERS[REQUEST_TIERS.length - 1];
    if (Number.isFinite(budgetValue) && budgetValue > 0 && budgetValue < tierConfig.ownerMin) {
      setStatus({ type: 'error', text: `该期限档位最低 ${tierConfig.ownerMin} 元起。` });
      return;
    }
    const creatorFloorValue = creatorFloor ? Number(creatorFloor) : NaN;
    if (Number.isFinite(creatorFloorValue) && creatorFloorValue > 0) {
      if (!Number.isFinite(budgetValue) || budgetValue <= 0) {
        setStatus({ type: 'error', text: '设置跟购底价需先填写预算。' });
        return;
      }
      const maxFloor = Math.max(5, Math.floor(budgetValue * 0.6));
      if (creatorFloorValue < 5) {
        setStatus({ type: 'error', text: '跟购底价最低 5 元。' });
        return;
      }
      if (creatorFloorValue > maxFloor) {
        setStatus({ type: 'error', text: `跟购底价不可高于 ${maxFloor} 元。` });
        return;
      }
    }
    setSubmitting(true);
    try {
      const payload = {
        course: trimmedTitle,
        keyword: trimmedIntro,
        budget: !Number.isNaN(budgetValue) && budgetValue > 0 ? Math.round(budgetValue * 100) : null,
        urgencyTier,
        creatorFloor: !Number.isNaN(creatorFloorValue) && creatorFloorValue > 0 ? Math.round(creatorFloorValue * 100) : null,
        previewRequirement: previewRequirement.trim() || null,
        school: school || null,
        college: college || null,
        major: major || null,
      };
      const data = await createMaterialRequest(payload);
      if (data.paymentRequired) {
        if (!data.form) {
          throw new Error('支付表单获取失败');
        }
        setStatus({ type: 'success', text: '订单已创建，正在跳转支付…' });
        setPayFormHtml(data.form as string);
        return;
      }
      setTitle('');
      setIntro('');
      setBudget('');
      setUrgencyTier('FLEX');
      setCreatorFloor('');
      setPreviewRequirement('');
      setSchool('');
      setCollege('');
      setMajor('');
      setStatus({ type: 'success', text: '发布成功！你可以回到首页查看求购列表。' });
    } catch (error: unknown) {
      setStatus({ type: 'error', text: toErrorMessage(error, '发布失败') });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container request-new-page">
        <div className="request-new-layout">
          <aside className="me-sidebar request-new-sidebar">
            <div className="me-sidebar__brand">求购发布</div>
            <div className="me-sidebar__group">
              <div className="me-sidebar__label">页面导航</div>
              <nav className="me-sidebar__items" aria-label="求购发布页面导航">
                {REQUEST_NAV_ITEMS.map((item) => (
                  <a
                    key={item.id}
                    href={`#${item.id}`}
                    className={`me-sidebar__item${activeSection === item.id ? ' active' : ''}`}
                    onClick={(event) => {
                      event.preventDefault();
                      jumpToSection(item.id);
                    }}
                  >
                    <span className="me-sidebar__indicator" />
                    <span className="me-sidebar__text">{item.label}</span>
                  </a>
                ))}
              </nav>
            </div>
          </aside>

          <section className="card request-new-shell">
            <div className="request-new-shell__header" id="request-overview">
              <div>
                <h2>发布求购需求</h2>
                <p className="help-text">按模块填写信息，发布后将进入求购列表并支持跟购。</p>
              </div>
              <div className="request-new-shell__capsules">
                <span>标题上限 {MAX_TITLE_LENGTH} 字</span>
                <span>简介上限 {MAX_DESC_LENGTH} 字</span>
                <span>当前期限最低 {activeTier.ownerMin} 元</span>
              </div>
            </div>

            <form className="form-grid request-new-form" onSubmit={handleSubmit}>
              <div className="request-form-section full" id="request-basic">
                <div className="request-form-section__title">基础信息</div>
                <p className="request-form-section__hint">清晰描述你需要的资料范围和用途。</p>
              </div>
            <div className="form-item full">
              <label htmlFor="request-title">标题</label>
              <input
                id="request-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={MAX_TITLE_LENGTH}
                placeholder="例如：通信原理期末速成"
                required
              />
              <p className="help-text">
                已输入 {title.length}/{MAX_TITLE_LENGTH}
              </p>
            </div>
            <div className="form-item full">
              <label htmlFor="request-intro">简介</label>
              <textarea
                id="request-intro"
                value={intro}
                onChange={(e) => setIntro(e.target.value)}
                maxLength={MAX_DESC_LENGTH}
                rows={4}
                placeholder="描述你想要的资料类型、用途或具体章节"
                required
              />
              <p className="help-text">
                已输入 {intro.length}/{MAX_DESC_LENGTH}
              </p>
            </div>
            <div className="form-item full">
              <label htmlFor="request-preview-rule">预览要求（可选）</label>
              <textarea
                id="request-preview-rule"
                value={previewRequirement}
                onChange={(e) => setPreviewRequirement(e.target.value)}
                maxLength={MAX_PREVIEW_REQUIREMENT_LENGTH}
                rows={3}
                placeholder="例如：需包含目录页/关键公式页/清晰页码等"
              />
              <p className="help-text">
                已输入 {previewRequirement.length}/{MAX_PREVIEW_REQUIREMENT_LENGTH}
              </p>
            </div>

              <div className="request-form-section full" id="request-budget">
                <div className="request-form-section__title">预算与期限</div>
                <p className="request-form-section__hint">预算越合理，求购曝光与应答效率通常越高。</p>
              </div>
            <div className="form-item">
              <label htmlFor="request-budget-input">预算（元，可选，当前档位最低 {activeTier.ownerMin} 元）</label>
              <input
                id="request-budget-input"
                type="number"
                min={activeTier.ownerMin}
                step="1"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                placeholder="例如 10"
              />
            </div>
            <div className="form-item">
              <label htmlFor="request-tier">交付期限</label>
              <select
                id="request-tier"
                value={urgencyTier}
                onChange={(e) => setUrgencyTier(e.target.value as RequestTierValue)}
              >
                {REQUEST_TIERS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}（最低 {item.ownerMin} 元）
                  </option>
                ))}
              </select>
              <p className="help-text">发起价最低要求已按期限自动调整。</p>
            </div>
            <div className="form-item">
              <label htmlFor="request-floor">跟购底价下限（元，可选）</label>
              <input
                id="request-floor"
                type="number"
                min="5"
                step="1"
                value={creatorFloor}
                onChange={(e) => setCreatorFloor(e.target.value)}
                placeholder="例如 6"
                disabled={!budget}
              />
              <p className="help-text">不高于预算的 60%，且最低 5 元。</p>
            </div>

              <div className="request-form-section full" id="request-scope">
                <div className="request-form-section__title">匹配范围</div>
                <p className="request-form-section__hint">选填学校/学院/专业，用于优先推荐给对口用户。</p>
              </div>
            <div className="form-item">
              <label htmlFor="request-school">学校（可选）</label>
              <select
                id="request-school"
                value={school}
                onChange={(e) => {
                  const value = e.target.value;
                  setSchool(value);
                  if (!value) {
                    setCollege('');
                    setMajor('');
                  }
                }}
              >
                <option value="">不指定</option>
                <option value={SUPPORTED_SCHOOL}>{SUPPORTED_SCHOOL}</option>
              </select>
            </div>
            <div className="form-item">
              <label htmlFor="request-college">学院（可选）</label>
              <select
                id="request-college"
                value={college}
                onChange={(e) => {
                  const value = e.target.value;
                  setCollege(value);
                  if (!value) {
                    setMajor('');
                  }
                }}
                disabled={!school}
              >
                <option value="">{school ? '不指定' : '请先选择学校'}</option>
                {SUPPORTED_COLLEGES.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-item">
              <label htmlFor="request-major">专业（可选）</label>
              <select
                id="request-major"
                value={major}
                onChange={(e) => setMajor(e.target.value)}
                disabled={!college}
              >
                <option value="">{college ? '不指定' : '请先选择学院'}</option>
                {SUPPORTED_MAJORS.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-item full">
              <div className="inline-group wrap">
                <button className="button primary" type="submit" disabled={submitting}>
                  {submitting ? '发布中...' : '发布求购'}
                </button>
                <Link className="button ghost" href="/">
                  返回首页
                </Link>
              </div>
              {status && (
                <p className={status.type === 'error' ? 'error-text' : 'success-text'}>{status.text}</p>
              )}
            </div>
            </form>

            <div ref={formContainerRef} style={{ display: 'none' }} />
          </section>
        </div>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<RequestNewProps> = async (ctx) => {
  const session = readSession(ctx.req);
  if (!session.user) {
    return {
      redirect: {
        destination: `/login?next=${encodeURIComponent('/requests/new')}`,
        permanent: false,
      },
    };
  }
  return {
    props: {
      user: session.user,
    },
  };
};
