import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import { hasRole, readSession } from '../lib/auth';
import { formatDateTime } from '../lib/format';
import { fetchOptionalSessionUser } from '../lib/sessionApi';
import { materialPath } from '../lib/slug';
import { fetchStudyHubAgentMaterial, requestStudyHubAgentRecommendations } from '../lib/studyHubAgentApi';
import { RoleMask, SessionUser } from '../types/user';
import { MaterialListItem } from '../types/material';
import SafeMarkdown from './SafeMarkdown';

type EyeOffset = { x: number; y: number };
type AiRecommendation = {
  material_id: number;
  title?: string;
  tags?: string[];
  reason?: string;
  explain?: string;
  match_reason?: string;
  note?: string;
  summary?: string;
  citations?: string[];
};

const POS_STORAGE_KEY = 'floating-sidebar-pos';
const HAT_STORAGE_KEY = 'studyhub-bot-hat';
const MOBILE_BREAKPOINT = 720;
const MOBILE_EDGE_GAP = 16;
const MOBILE_BUBBLE_SIZE = 50;
const BOT_HAT_IDS = ['santa', 'graduation', 'party', 'wizard', 'none'] as const;
type BotHat = (typeof BOT_HAT_IDS)[number];
const BOT_HATS: { id: BotHat; label: string; previewClass: string }[] = [
  { id: 'santa', label: '圣诞帽', previewClass: 'hat-preview-santa' },
  { id: 'graduation', label: '学士帽', previewClass: 'hat-preview-graduation' },
  { id: 'party', label: '派对帽', previewClass: 'hat-preview-party' },
  { id: 'wizard', label: '魔法帽', previewClass: 'hat-preview-wizard' },
  { id: 'none', label: '不佩戴', previewClass: 'hat-preview-none' },
];

function isBotHat(value: string | null): value is BotHat {
  return BOT_HAT_IDS.includes(value as BotHat);
}

export default function FloatingSidebar() {
  const { user: sessionUser } = readSession();
  const [user, setUser] = useState<SessionUser | null>(sessionUser);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [wardrobeOpen, setWardrobeOpen] = useState(false);
  const [sidebarPosition, setSidebarPosition] = useState({ x: 60, y: 220 });
  const [selectedHat, setSelectedHat] = useState<BotHat>('santa');
  const sidebarRef = useRef<HTMLDivElement>(null);
  const bubbleRef = useRef<HTMLButtonElement>(null);
  const draggingRef = useRef(false);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const dragMovedRef = useRef(false);
  const suppressClickRef = useRef(false);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  const [bubbleMood, setBubbleMood] = useState<'neutral' | 'happy' | 'wink'>('neutral');
  const [eyeOffset, setEyeOffset] = useState<EyeOffset>({ x: 0, y: 0 });
  const eyeTrackingEnabled = true; // 眼睛跟随默认开启（无开关）
  const lastFetchRef = useRef<number>(0);
  const [chatQuery, setChatQuery] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [chatStage, setChatStage] = useState('');
  const [chatError, setChatError] = useState<string | null>(null);
  const [aiAnswer, setAiAnswer] = useState('');
  const [aiContextQuery, setAiContextQuery] = useState('');
  const [aiRecommendations, setAiRecommendations] = useState<AiRecommendation[]>([]);
  const [aiFollowups, setAiFollowups] = useState<string[]>([]);
  const [aiDetails, setAiDetails] = useState<Record<number, MaterialListItem>>({});

  const getMobileRestingPosition = useCallback(() => {
    if (typeof window === 'undefined') return null;
    if (window.innerWidth > MOBILE_BREAKPOINT) return null;
    const mobileNav = document.querySelector<HTMLElement>('.mobile-bottom-nav');
    const mobileNavTop = mobileNav?.getBoundingClientRect().top;
    const availableBottom = mobileNavTop && mobileNavTop > 0 ? mobileNavTop : window.innerHeight - 76;
    return {
      x: Math.max(MOBILE_EDGE_GAP, window.innerWidth - MOBILE_BUBBLE_SIZE - MOBILE_EDGE_GAP),
      y: Math.max(96, availableBottom - MOBILE_BUBBLE_SIZE - MOBILE_EDGE_GAP),
    };
  }, []);

  const clampSidebarPosition = useCallback((x: number, y: number, panelWidth?: number, panelHeight?: number) => {
    if (typeof window === 'undefined') return { x, y };
    const width = panelWidth ?? sidebarRef.current?.offsetWidth ?? 320;
    const height = panelHeight ?? sidebarRef.current?.offsetHeight ?? 360;
    const minX = 16;
    const minY = 96;
    const maxX = Math.max(minX, window.innerWidth - width - 16);
    const mobileNav = window.innerWidth <= MOBILE_BREAKPOINT
      ? document.querySelector<HTMLElement>('.mobile-bottom-nav')
      : null;
    const mobileNavTop = mobileNav?.getBoundingClientRect().top;
    const availableBottom = mobileNavTop && mobileNavTop > 0 ? mobileNavTop : window.innerHeight;
    const maxY = Math.max(minY, availableBottom - height - MOBILE_EDGE_GAP);
    return {
      x: Math.min(Math.max(minX, x), maxX),
      y: Math.min(Math.max(minY, y), maxY),
    };
  }, []);

  const getSidebarClampSize = useCallback(() => {
    if (!sidebarOpen) {
      return {
        width: bubbleRef.current?.offsetWidth ?? 52,
        height: bubbleRef.current?.offsetHeight ?? 52,
      };
    }
    return {
      width: sidebarRef.current?.offsetWidth ?? 320,
      height: sidebarRef.current?.offsetHeight ?? 360,
    };
  }, [sidebarOpen]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mobileRestingPosition = getMobileRestingPosition();
    try {
      const saved = window.localStorage.getItem(POS_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (typeof parsed.x === 'number' && typeof parsed.y === 'number') {
          const next =
            mobileRestingPosition && (parsed.y < mobileRestingPosition.y - 80 || parsed.x < 80)
              ? mobileRestingPosition
              : parsed;
          const size = getSidebarClampSize();
          setSidebarPosition(() => clampSidebarPosition(next.x, next.y, size.width, size.height));
          return;
        }
      }
    } catch {
      // ignore
    }
    const size = getSidebarClampSize();
    setSidebarPosition((pos) => {
      const next = mobileRestingPosition ?? pos;
      return clampSidebarPosition(next.x, next.y, size.width, size.height);
    });
  }, [clampSidebarPosition, getMobileRestingPosition, getSidebarClampSize]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const saved = window.localStorage.getItem(HAT_STORAGE_KEY);
      if (isBotHat(saved)) {
        setSelectedHat(saved);
      }
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    setSidebarPosition((pos) =>
      clampSidebarPosition(pos.x, pos.y, getSidebarClampSize().width, getSidebarClampSize().height)
    );
  }, [sidebarOpen, clampSidebarPosition, getSidebarClampSize]);

  useEffect(() => {
    const handler = () => {
      const size = getSidebarClampSize();
      setSidebarPosition((pos) =>
        clampSidebarPosition(pos.x, pos.y, size.width, size.height)
      );
    };
    if (typeof window === 'undefined') return undefined;
    window.addEventListener('resize', handler);
    window.visualViewport?.addEventListener('resize', handler);
    window.visualViewport?.addEventListener('scroll', handler);
    return () => {
      window.removeEventListener('resize', handler);
      window.visualViewport?.removeEventListener('resize', handler);
      window.visualViewport?.removeEventListener('scroll', handler);
    };
  }, [clampSidebarPosition, getSidebarClampSize]);


  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    let animationFrame: number | null = null;
    let sampleTimer: number | null = null;
    const lastPointer = { x: 0, y: 0 };
    let hasPointer = false;
    const target = { x: 0, y: 0 };

    const pointerHandler = (event: PointerEvent) => {
      hasPointer = true;
      lastPointer.x = event.clientX;
      lastPointer.y = event.clientY;
    };

    const sampleTarget = () => {
      const bubble = bubbleRef.current;
      if (!bubble || !hasPointer) return;
      const rect = bubble.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const dx = lastPointer.x - centerX;
      const dy = lastPointer.y - centerY;
      const dist = Math.max(Math.hypot(dx, dy), 1);
      const maxOffset = 6; // px
      target.x = (dx / dist) * maxOffset;
      target.y = (dy / dist) * maxOffset;
    };

    const step = () => {
      setEyeOffset((prev) => {
        const lerp = 0.05;
        const nx = prev.x + (target.x - prev.x) * lerp;
        const ny = prev.y + (target.y - prev.y) * lerp;
        if (Math.abs(nx - target.x) < 0.01 && Math.abs(ny - target.y) < 0.01) {
          return { x: target.x, y: target.y };
        }
        return { x: nx, y: ny };
      });
      animationFrame = window.requestAnimationFrame(step);
    };

    window.addEventListener('pointermove', pointerHandler);
    sampleTimer = window.setInterval(sampleTarget, 150);
    animationFrame = window.requestAnimationFrame(step);

    return () => {
      window.removeEventListener('pointermove', pointerHandler);
      if (sampleTimer) window.clearInterval(sampleTimer);
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
    };
  }, []);

  const userRoleBadges = useMemo(() => {
    if (!user) return [];
    return [RoleMask.DEVELOPER, RoleMask.ADMIN, RoleMask.REVIEWER, RoleMask.CONTRIBUTOR, RoleMask.USER]
      .map((mask) => ({ mask, label: maskLabel(mask) }))
      .filter((role) => role.label && hasRole(user.roleMask, role.mask))
      .map((role) => role.label);
  }, [user]);
  const canShowAiRecommendations = useMemo(() => {
    if (!user) return false;
    return [RoleMask.CONTRIBUTOR, RoleMask.REVIEWER, RoleMask.ADMIN, RoleMask.DEVELOPER].some((role) =>
      hasRole(user.roleMask, role)
    );
  }, [user]);

  const loadData = useCallback(async () => {
    try {
      setUser(await fetchOptionalSessionUser());
      lastFetchRef.current = Date.now();
    } catch {
      // ignore fetch errors
    }
  }, []);

  useEffect(() => {
    const handleOpen = (event: Event) => {
      const custom = event as CustomEvent<string>;
      setSidebarOpen(custom.detail === 'toggle' ? (prev) => !prev : true);
      loadData();
    };
    window.addEventListener('floating-sidebar:toggle', handleOpen as EventListener);
    return () => window.removeEventListener('floating-sidebar:toggle', handleOpen as EventListener);
  }, [loadData]);

  const extractAiJson = (raw: string) => {
    if (!raw) return '';
    const start = raw.indexOf('<json>');
    const end = raw.indexOf('</json>');
    if (start >= 0 && end > start) {
      return raw.slice(start + 6, end).trim();
    }
    return raw.trim();
  };

  const normalizeRecommendations = (value: unknown) => {
    if (!Array.isArray(value)) return [] as AiRecommendation[];
    return value
      .map((item) => {
        if (!item || typeof item !== 'object') return null;
        const rec = item as Record<string, unknown>;
        const idRaw = rec.material_id ?? rec.materialId ?? rec.id;
        const id = Number(idRaw);
        if (!Number.isFinite(id)) return null;
        return {
          material_id: id,
          title: typeof rec.title === 'string' ? rec.title : undefined,
          tags: Array.isArray(rec.tags) ? (rec.tags as string[]) : undefined,
          reason: typeof rec.reason === 'string' ? rec.reason : undefined,
          explain: typeof rec.explain === 'string' ? rec.explain : undefined,
          match_reason: typeof rec.match_reason === 'string' ? rec.match_reason : undefined,
          note: typeof rec.note === 'string' ? rec.note : undefined,
          summary: typeof rec.summary === 'string' ? rec.summary : undefined,
          citations: Array.isArray(rec.citations) ? (rec.citations as string[]) : undefined,
        } as AiRecommendation;
      })
      .filter((item): item is AiRecommendation => Boolean(item));
  };

  const loadMaterialDetail = useCallback(async (materialId: number) => {
    if (aiDetails[materialId]) return;
    try {
      const detail = await fetchStudyHubAgentMaterial(materialId);
      setAiDetails((prev) => ({ ...prev, [materialId]: detail }));
    } catch {
      // ignore detail fetch errors
    }
  }, [aiDetails]);

  const handleAiSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!chatQuery.trim() || chatLoading) return;
      if (!user) {
        setChatError('登录后可使用资料推荐');
        return;
      }
      const currentQuery = chatQuery.trim();
      setChatLoading(true);
      setChatStage('理解问题中');
      setChatError(null);
      try {
        const data = await requestStudyHubAgentRecommendations(currentQuery, aiContextQuery);
        const output = data.output;
        if (!output || typeof output !== 'string') {
          setChatError('AI 响应为空，请稍后再试');
          setChatLoading(false);
          return;
        }
        const parsed = JSON.parse(extractAiJson(output));
        const recs = normalizeRecommendations(parsed?.recommendations);
        const answer = typeof parsed?.answer === 'string' ? parsed.answer.trim() : '';
        const followups = normalizeAiFollowups(parsed?.followup_questions, currentQuery);
        setAiAnswer(answer);
        setAiRecommendations(recs);
        setAiFollowups(followups);
        setAiContextQuery(buildSidebarAiContext(currentQuery, answer, recs));
        await Promise.all(recs.map((rec) => loadMaterialDetail(rec.material_id)));
        if (recs.length === 0 && !answer) {
          setChatError('没有匹配到合适的资料，可以换个关键词试试');
        }
      } catch (err) {
        setChatError(err instanceof Error ? err.message : '推荐失败，请稍后重试');
      } finally {
        setChatLoading(false);
        setChatStage('');
      }
    },
    [chatQuery, chatLoading, user, loadMaterialDetail, aiContextQuery]
  );

  const pickRecommendationReason = (rec: AiRecommendation) =>
    rec.reason || rec.explain || rec.match_reason || rec.note || rec.summary || '';

  useEffect(() => {
    let cancelled = false;
    loadData();
    return () => {
      cancelled = true;
    };
  }, [loadData]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        const now = Date.now();
        if (now - lastFetchRef.current > 15000) {
          loadData();
        }
      }
    };
    if (typeof document === 'undefined') return;
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('focus', handleVisibility);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('focus', handleVisibility);
    };
  }, [loadData]);


  const handlePointerMoveDrag = useCallback(
    (event: PointerEvent) => {
      const start = dragStartRef.current;
      if (!start) return;
      const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
      // 启动拖拽需要轻微移动，避免点按触发拖拽
      if (!draggingRef.current && distance < 6) {
        return;
      }
      if (!draggingRef.current) {
        draggingRef.current = true;
        dragOffsetRef.current = {
          x: start.x - sidebarPosition.x,
          y: start.y - sidebarPosition.y,
        };
      }
      dragMovedRef.current = true;
      const { x, y } = dragOffsetRef.current;
      const nextX = event.clientX - x;
      const nextY = event.clientY - y;
      setSidebarPosition((pos) => {
        const next = clampSidebarPosition(nextX, nextY);
        try {
          window.localStorage.setItem(POS_STORAGE_KEY, JSON.stringify(next));
        } catch {
          // ignore
        }
        return next;
      });
    },
    [clampSidebarPosition, sidebarPosition.x, sidebarPosition.y]
  );

  const handlePointerUp = useCallback(() => {
    document.removeEventListener('pointermove', handlePointerMoveDrag);
    document.removeEventListener('pointerup', handlePointerUp);
    document.removeEventListener('pointercancel', handlePointerUp);
    dragStartRef.current = null;
    if (!draggingRef.current) {
      suppressClickRef.current = false;
      return;
    }
    draggingRef.current = false;
    suppressClickRef.current = dragMovedRef.current;
    dragMovedRef.current = false;
    setBubbleMood('happy');
    window.setTimeout(() => setBubbleMood('neutral'), 1200);
    if (suppressClickRef.current) {
      window.setTimeout(() => {
        suppressClickRef.current = false;
      }, 0);
    }
  }, [handlePointerMoveDrag]);

  const startSidebarDrag = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      event.preventDefault();
      dragStartRef.current = { x: event.clientX, y: event.clientY };
      draggingRef.current = false;
      dragMovedRef.current = false;
      if (event.currentTarget.setPointerCapture) {
        try {
          event.currentTarget.setPointerCapture(event.pointerId);
        } catch {
          // ignore
        }
      }
      document.addEventListener('pointermove', handlePointerMoveDrag);
      document.addEventListener('pointerup', handlePointerUp);
      document.addEventListener('pointercancel', handlePointerUp);
      setBubbleMood('wink');
    },
    [handlePointerMoveDrag, handlePointerUp]
  );

  const formatNoteTime = (value: string) => formatDateTime(value) || value;

  const selectHat = useCallback((hat: BotHat) => {
    setSelectedHat(hat);
    try {
      window.localStorage.setItem(HAT_STORAGE_KEY, hat);
    } catch {
      // ignore
    }
  }, []);

  const eyeStyle = {
    ['--eye-x' as React.CSSProperties['animation']]: `${eyeTrackingEnabled ? eyeOffset.x : 0}px`,
    ['--eye-y' as React.CSSProperties['animation']]: `${eyeTrackingEnabled ? eyeOffset.y : 0}px`,
  };

  const loginLink = { pathname: '/login' };
  const registerLink = { pathname: '/login', query: { mode: 'register' } };
  const selectedHatLabel = BOT_HATS.find((hat) => hat.id === selectedHat)?.label || '圣诞帽';
  const wardrobeModal = wardrobeOpen ? (
    <div
      className="floating-wardrobe-mask"
      role="presentation"
      onPointerDown={(event) => event.stopPropagation()}
      onClick={() => setWardrobeOpen(false)}
    >
      <div
        className="floating-wardrobe-modal"
        role="dialog"
        aria-modal="true"
        aria-label="StudyHub Bot 衣帽间"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="floating-wardrobe-modal__header">
          <div>
            <span className="floating-wardrobe-modal__eyebrow">StudyHub Bot</span>
            <h3>衣帽间</h3>
          </div>
          <button
            type="button"
            className="floating-wardrobe-modal__close"
            aria-label="关闭衣帽间"
            onClick={() => setWardrobeOpen(false)}
          >
            ×
          </button>
        </div>
        <div className="sidebar-hat-options" role="radiogroup" aria-label="StudyHub Bot 帽子">
          {BOT_HATS.map((hat) => (
            <button
              key={hat.id}
              type="button"
              className={`sidebar-hat-option ${selectedHat === hat.id ? 'is-active' : ''}`}
              role="radio"
              aria-checked={selectedHat === hat.id}
              onClick={() => selectHat(hat.id)}
            >
              <span className={`sidebar-hat-option__preview ${hat.previewClass}`} aria-hidden="true" />
              <span>{hat.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  ) : null;

  return (
    <>
      <aside
        ref={sidebarRef}
        className={`floating-sidebar ${sidebarOpen ? 'open' : ''} hat-${selectedHat}`}
        style={{
          left: sidebarPosition.x,
          top: sidebarPosition.y,
        }}
      >
        <button
          ref={bubbleRef}
          type="button"
          className={`floating-sidebar__bubble mood-${bubbleMood}`}
          aria-expanded={sidebarOpen}
          aria-label={sidebarOpen ? '收起浮窗' : '打开浮窗'}
          style={eyeStyle}
          onPointerDown={startSidebarDrag}
          onClick={() => {
            if (suppressClickRef.current) return;
            setSidebarOpen((prev) => !prev);
          }}
        >
          <span className="floating-sidebar__hat" aria-hidden="true" />
          <span className="floating-face" aria-hidden="true" />
        </button>
        {sidebarOpen && (
          <div className="floating-sidebar__panel">
            <div className="floating-sidebar__header" onPointerDown={startSidebarDrag} role="presentation">
              <span>StudyHub Bot</span>
              <button
                type="button"
                className="floating-sidebar__close"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => setSidebarOpen(false)}
                aria-label="收起浮窗"
              >
                ×
              </button>
            </div>
            <div className="sidebar-body">
              <div className="sidebar-section">
                {user ? (
                  <>
                    <div className="sidebar-profile">
                      <div className="sidebar-avatar" aria-hidden="true">
                        {(user.nickname || user.username || '用户').charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <strong>{user.nickname}</strong>
                        {user.username && <span className="sidebar-username">@{user.username}</span>}
                      </div>
                    </div>
                    {userRoleBadges.length > 0 && (
                      <div className="sidebar-roles">
                        {userRoleBadges.map((role) => (
                          <span key={role}>{role}</span>
                        ))}
                      </div>
                    )}
                    <p className="sidebar-muted">可在“我的”中查看投稿、购买记录与校园集市状态。</p>
                    <button
                      type="button"
                      className="button ghost small full-width sidebar-wardrobe-button"
                      onPointerDown={(event) => event.stopPropagation()}
                      onClick={() => setWardrobeOpen(true)}
                    >
                      衣帽间 · {selectedHatLabel}
                    </button>
                    <Link className="button ghost small full-width" href="/me">
                      打开我的页面
                    </Link>
                  </>
                ) : (
                  <>
                    <div className="sidebar-profile">
                      <div className="sidebar-avatar" aria-hidden="true">
                        {(user?.nickname || user?.username || '用户').charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <strong>未登录</strong>
                        <span className="sidebar-username">
                          <Link className="login-link" href="/login">登录</Link>后解锁个人中心
                        </span>
                      </div>
                    </div>
                    <p className="sidebar-muted">
                      <Link className="login-link" href="/login">登录</Link>后可同步购买、投稿、批量下载记录。
                    </p>
                    <div className="sidebar-auth-actions">
                      <Link className="button primary small" href={loginLink}>
                        登录
                      </Link>
                      <Link className="button ghost small" href={registerLink}>
                        注册
                      </Link>
                    </div>
                    <button
                      type="button"
                      className="button ghost small full-width sidebar-wardrobe-button"
                      onPointerDown={(event) => event.stopPropagation()}
                      onClick={() => setWardrobeOpen(true)}
                    >
                      衣帽间 · {selectedHatLabel}
                    </button>
                  </>
                )}
              </div>
              {canShowAiRecommendations && (
                <div className="sidebar-section sidebar-chat">
                  <h4 className="sidebar-section-title">AI 资料推荐</h4>
                  <p className="sidebar-muted">输入关键词，AI 只会推荐资料库内的内容。</p>
                  {chatError && <p className="sidebar-chat__error">{chatError}</p>}
                  {chatLoading && (
                    <div className="sidebar-chat__loading" role="status" aria-live="polite">
                      <span className="sidebar-chat__loading-dot" aria-hidden="true" />
                      <span>{chatStage || '处理中'}</span>
                    </div>
                  )}
                  {aiAnswer && (
                    <div className="sidebar-ai-answer">
                      <SafeMarkdown>{aiAnswer}</SafeMarkdown>
                    </div>
                  )}
                  {aiRecommendations.length > 0 && (
                    <ul className="sidebar-ai-list">
                      {aiRecommendations.map((rec) => {
                        const detail = aiDetails[rec.material_id];
                        const title = detail?.title || rec.title || `资料 #${rec.material_id}`;
                        const reason = pickRecommendationReason(rec);
                        const link = materialPath(rec.material_id, detail?.title || rec.title);
                        const tags = detail?.tags || rec.tags || [];
                        return (
                          <li key={rec.material_id} className="sidebar-ai-card">
                            <div className="sidebar-ai-title">
                              <Link href={link}>{title}</Link>
                            </div>
                            <div className="sidebar-ai-meta">
                              <span>{detail?.school || 'StudyHub'}</span>
                              {detail?.gradeValue && <span>· {detail.gradeValue}</span>}
                              {detail && (
                                <span className="sidebar-ai-price">
                                  {detail.free ? '免费' : `¥${detail.price?.toFixed(2)}`}
                                </span>
                              )}
                            </div>
                            {tags.length > 0 && (
                              <div className="sidebar-ai-tags">
                                {tags.slice(0, 4).map((tag) => (
                                  <span key={tag} className="sidebar-ai-pill">{tag}</span>
                                ))}
                              </div>
                            )}
                            {reason && <p className="sidebar-ai-reason">{reason}</p>}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                  {aiFollowups.length > 0 && (
                    <div className="sidebar-ai-followups">
                      <span>可以补充：</span>
                      {aiFollowups.map((item, index) => (
                        <button
                          key={`${item}-${index}`}
                          type="button"
                          className="sidebar-ai-followup"
                          onClick={() => {
                            setChatQuery(item);
                            setChatError(null);
                          }}
                        >
                          {item}
                        </button>
                      ))}
                    </div>
                  )}
                  <form className="sidebar-chat__form" onSubmit={handleAiSubmit}>
                    <input
                      className="sidebar-chat__input"
                      value={chatQuery}
                      onChange={(event) => setChatQuery(event.target.value)}
                      placeholder="例如：信号与系统 期末 真题"
                      disabled={chatLoading}
                    />
                    <button type="submit" className="button primary small" disabled={chatLoading || !chatQuery.trim()}>
                      {chatLoading ? '推荐中' : '推荐'}
                    </button>
                  </form>
                </div>
              )}
            </div>
          </div>
        )}
      </aside>
      {wardrobeModal && typeof document !== 'undefined' ? createPortal(wardrobeModal, document.body) : null}
    </>
  );
}

function maskLabel(mask: RoleMask): string | null {
  switch (mask) {
    case RoleMask.DEVELOPER:
      return '开发者';
    case RoleMask.ADMIN:
      return '管理员';
    case RoleMask.REVIEWER:
      return '审核员';
    case RoleMask.CONTRIBUTOR:
      return '投稿者';
    case RoleMask.USER:
      return '普通用户';
    default:
      return null;
  }
}

function normalizeAiFollowups(value: unknown, currentQuery: string) {
  if (!Array.isArray(value)) return [];
  const currentKey = followupKey(currentQuery);
  const seen = new Set<string>();
  return value
    .map((item) => (typeof item === 'string' ? item.trim().replace(/\s+/g, ' ') : ''))
    .filter((item): item is string => {
      if (!item) return false;
      const key = followupKey(item);
      if (!key || key === currentKey || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 3);
}

function buildSidebarAiContext(query: string, answer: string, recommendations: AiRecommendation[]) {
  const titles = recommendations
    .map((item) => item.title)
    .filter((title): title is string => Boolean(title && title.trim()))
    .slice(0, 4);
  return [
    `用户：${redactSidebarContext(query).slice(0, 220)}`,
    answer ? `助手：${redactSidebarContext(answer).slice(0, 420)}` : '',
    titles.length > 0 ? `推荐资料：${titles.map(redactSidebarContext).join('；')}` : '',
  ]
    .filter(Boolean)
    .join(' ')
    .slice(-1000);
}

function followupKey(value: string) {
  return value.replace(/[^\u4e00-\u9fa5A-Za-z0-9]+/g, '').toLowerCase();
}

function redactSidebarContext(value: string) {
  return value
    .replace(/https?:\/\/[^\s,;，；。]+|www\.[^\s,;，；。]+/gi, '[redacted-url]')
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[redacted-email]')
    .replace(/(^|[^\d])(1[3-9]\d{9})(?!\d)/g, '$1[redacted-phone]');
}
