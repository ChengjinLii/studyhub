import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { hasRole, readSession } from '../lib/auth';
import { fetchBackend } from '../lib/apiBase';
import { materialPath } from '../lib/slug';
import { RoleMask, SessionUser } from '../types/user';
import { MaterialListItem } from '../types/material';

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

export default function FloatingSidebar() {
  const { user: sessionUser } = readSession();
  const [user, setUser] = useState<SessionUser | null>(sessionUser);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarPosition, setSidebarPosition] = useState({ x: 60, y: 220 });
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
  const [chatError, setChatError] = useState<string | null>(null);
  const [aiRecommendations, setAiRecommendations] = useState<AiRecommendation[]>([]);
  const [aiFollowups, setAiFollowups] = useState<string[]>([]);
  const [aiDetails, setAiDetails] = useState<Record<number, MaterialListItem>>({});

  const clampSidebarPosition = useCallback((x: number, y: number, panelWidth?: number, panelHeight?: number) => {
    if (typeof window === 'undefined') return { x, y };
    const width = panelWidth ?? sidebarRef.current?.offsetWidth ?? 320;
    const height = panelHeight ?? sidebarRef.current?.offsetHeight ?? 360;
    const minX = 16;
    const minY = 96;
    const maxX = Math.max(minX, window.innerWidth - width - 16);
    const maxY = Math.max(minY, window.innerHeight - height - 16);
    return {
      x: Math.min(Math.max(minX, x), maxX),
      y: Math.min(Math.max(minY, y), maxY),
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const saved = window.localStorage.getItem(POS_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (typeof parsed.x === 'number' && typeof parsed.y === 'number') {
          setSidebarPosition((pos) => clampSidebarPosition(parsed.x, parsed.y));
        }
      }
    } catch {
      // ignore
    }
    const panelWidth = sidebarRef.current?.offsetWidth ?? 280;
    const panelHeight = sidebarRef.current?.offsetHeight ?? 320;
    setSidebarPosition((pos) => clampSidebarPosition(pos.x, pos.y, panelWidth, panelHeight));
  }, [clampSidebarPosition]);

  useEffect(() => {
    setSidebarPosition((pos) =>
      clampSidebarPosition(pos.x, pos.y, sidebarRef.current?.offsetWidth, sidebarRef.current?.offsetHeight)
    );
  }, [sidebarOpen, clampSidebarPosition]);

  useEffect(() => {
    const handler = () => {
      setSidebarPosition((pos) =>
        clampSidebarPosition(pos.x, pos.y, sidebarRef.current?.offsetWidth, sidebarRef.current?.offsetHeight)
      );
    };
    if (typeof window === 'undefined') return undefined;
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, [clampSidebarPosition]);


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

  useEffect(() => {
    const handleOpen = (event: Event) => {
      const custom = event as CustomEvent<string>;
      setSidebarOpen(custom.detail === 'toggle' ? (prev) => !prev : true);
      loadData();
    };
    window.addEventListener('floating-sidebar:toggle', handleOpen as EventListener);
    return () => window.removeEventListener('floating-sidebar:toggle', handleOpen as EventListener);
  }, []);

  const loadData = useCallback(async () => {
    let cancelled = false;

    const fetchJson = async (path: string, init?: RequestInit) => {
      const resp = await fetchBackend(path, init);
      const json = await resp.json();
      return { resp, json };
    };

    try {
      const { resp: sessionResp, json: sessionJson } = await fetchJson('/session');

      if (!cancelled && sessionResp.ok && sessionJson?.data?.user) {
        setUser(sessionJson.data.user);
      } else if (!cancelled && (sessionResp.status === 401 || sessionResp.status === 403)) {
        setUser(null);
      }
      lastFetchRef.current = Date.now();
    } catch {
      // ignore fetch errors
    }
    return () => {
      cancelled = true;
    };
  }, []);

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
      const resp = await fetchBackend(`/materials/${materialId}`);
      const json = await resp.json().catch(() => null);
      if (!resp.ok || !json?.ok || !json.data) return;
      setAiDetails((prev) => ({ ...prev, [materialId]: json.data }));
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
      setChatLoading(true);
      setChatError(null);
      try {
        const resp = await fetchBackend('/ai/recommend', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: chatQuery.trim() }),
        });
        const json = await resp.json().catch(() => null);
        if (!resp.ok || !json?.ok) {
          setChatError(json?.msg || '推荐失败，请稍后重试');
          setChatLoading(false);
          return;
        }
        const output = json?.data?.output;
        if (!output || typeof output !== 'string') {
          setChatError('AI 响应为空，请稍后再试');
          setChatLoading(false);
          return;
        }
        const parsed = JSON.parse(extractAiJson(output));
        const recs = normalizeRecommendations(parsed?.recommendations);
        const followups = Array.isArray(parsed?.followup_questions)
          ? parsed.followup_questions.filter((item: unknown) => typeof item === 'string')
          : [];
        setAiRecommendations(recs);
        setAiFollowups(followups);
        await Promise.all(recs.map((rec) => loadMaterialDetail(rec.material_id)));
        if (recs.length === 0) {
          setChatError('没有匹配到合适的资料，可以换个关键词试试');
        }
      } catch (err) {
        setChatError(err instanceof Error ? err.message : '推荐失败，请稍后重试');
      } finally {
        setChatLoading(false);
      }
    },
    [chatQuery, chatLoading, user, loadMaterialDetail]
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

  const eyeStyle = {
    ['--eye-x' as React.CSSProperties['animation']]: `${eyeTrackingEnabled ? eyeOffset.x : 0}px`,
    ['--eye-y' as React.CSSProperties['animation']]: `${eyeTrackingEnabled ? eyeOffset.y : 0}px`,
  };

  const loginLink = { pathname: '/login' };
  const registerLink = { pathname: '/login', query: { mode: 'register' } };

  return (
    <aside
      ref={sidebarRef}
      className={`floating-sidebar ${sidebarOpen ? 'open' : ''}`}
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
            <span>我的浮窗</span>
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
                        <a className="login-link" href="/login">登录</a>后解锁个人中心
                      </span>
                    </div>
                  </div>
                  <p className="sidebar-muted">
                    <a className="login-link" href="/login">登录</a>后可同步购买、投稿、批量下载记录。
                  </p>
                  <div className="sidebar-auth-actions">
                    <Link className="button primary small" href={loginLink}>
                      登录
                    </Link>
                    <Link className="button ghost small" href={registerLink}>
                      注册
                    </Link>
                  </div>
                </>
              )}
            </div>
            <div className="sidebar-section sidebar-chat">
              <h4 className="sidebar-section-title">AI 资料推荐</h4>
              <p className="sidebar-muted">输入关键词，AI 只会推荐资料库内的内容。</p>
              {chatError && <p className="sidebar-chat__error">{chatError}</p>}
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
                      onClick={() => setChatQuery(item)}
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
                  placeholder={user ? '例如：信号与系统 期末 真题' : '登录后可使用'}
                  disabled={!user || chatLoading}
                />
                <button type="submit" className="button primary small" disabled={!user || chatLoading || !chatQuery.trim()}>
                  {chatLoading ? '推荐中' : '推荐'}
                </button>
              </form>
            </div>
          </div>
        </div>
      )}
    </aside>
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
