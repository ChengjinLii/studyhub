import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { hasRole } from '../lib/auth';
import { formatDateTime } from '../lib/format';
import { RoleMask } from '../types/user';
import { useSession } from './SessionProvider';

type EyeOffset = { x: number; y: number };

const POS_STORAGE_KEY = 'floating-sidebar-pos';
const HAT_STORAGE_KEY = 'studyhub-bot-hat';
const MOBILE_BREAKPOINT = 720;
const MOBILE_EDGE_GAP = 16;
const MOBILE_DOCK_GAP = 8;
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

const isTextEntryElement = (element: Element | null) => {
  if (element instanceof HTMLTextAreaElement) return !element.readOnly && !element.disabled;
  if (element instanceof HTMLElement && element.isContentEditable) return true;
  if (!(element instanceof HTMLInputElement) || element.readOnly || element.disabled) return false;
  return !['button', 'checkbox', 'color', 'file', 'hidden', 'radio', 'range', 'reset', 'submit'].includes(element.type);
};

export default function FloatingSidebar() {
  const router = useRouter();
  const { user, refreshSession } = useSession();
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
  const keyboardOriginRef = useRef<{ x: number; y: number } | null>(null);
  const [bubbleMood, setBubbleMood] = useState<'neutral' | 'happy' | 'wink'>('neutral');
  const [eyeOffset, setEyeOffset] = useState<EyeOffset>({ x: 0, y: 0 });
  const eyeTrackingEnabled = true; // 眼睛跟随默认开启（无开关）

  const getMobileRestingPosition = useCallback(() => {
    if (typeof window === 'undefined') return null;
    if (window.innerWidth > MOBILE_BREAKPOINT) return null;
    const blockers = Array.from(
      document.querySelectorAll<HTMLElement>('.mobile-bottom-nav, .mobile-detail-action-bar')
    )
      .map((element) => element.getBoundingClientRect().top)
      .filter((top) => top > 0 && top < window.innerHeight);
    const availableBottom = blockers.length > 0 ? Math.min(...blockers) : window.innerHeight - 76;
    const x = Math.max(MOBILE_DOCK_GAP, window.innerWidth - MOBILE_BUBBLE_SIZE - MOBILE_DOCK_GAP);
    let y = Math.max(96, availableBottom - MOBILE_BUBBLE_SIZE - MOBILE_EDGE_GAP);
    const obstacles = Array.from(
      document.querySelectorAll<HTMLElement>('main button, main a.button, main input, main textarea, main select')
    )
      .filter((element) => !element.closest('.floating-sidebar'))
      .map((element) => element.getBoundingClientRect())
      .filter((rect) => rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < availableBottom);

    for (let attempt = 0; attempt < 8; attempt += 1) {
      const collision = obstacles.find(
        (rect) =>
          x - 8 < rect.right &&
          x + MOBILE_BUBBLE_SIZE + 8 > rect.left &&
          y - 8 < rect.bottom &&
          y + MOBILE_BUBBLE_SIZE + 8 > rect.top
      );
      if (!collision) break;
      y = Math.max(96, collision.top - MOBILE_BUBBLE_SIZE - 12);
    }

    return { x, y };
  }, []);

  const clampSidebarPosition = useCallback((x: number, y: number, panelWidth?: number, panelHeight?: number) => {
    if (typeof window === 'undefined') return { x, y };
    const width = panelWidth ?? sidebarRef.current?.offsetWidth ?? 320;
    const height = panelHeight ?? sidebarRef.current?.offsetHeight ?? 360;
    const horizontalGap = window.innerWidth <= MOBILE_BREAKPOINT ? MOBILE_DOCK_GAP : 16;
    const minX = horizontalGap;
    const minY = 96;
    const maxX = Math.max(minX, window.innerWidth - width - horizontalGap);
    const blockers = window.innerWidth <= MOBILE_BREAKPOINT
      ? Array.from(document.querySelectorAll<HTMLElement>('.mobile-bottom-nav, .mobile-detail-action-bar'))
          .map((element) => element.getBoundingClientRect().top)
          .filter((top) => top > 0 && top < window.innerHeight)
      : [];
    const availableBottom = blockers.length > 0 ? Math.min(...blockers) : window.innerHeight;
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
    if (typeof window === 'undefined') return undefined;
    const frame = window.requestAnimationFrame(() => {
      const size = getSidebarClampSize();
      const restingPosition = getMobileRestingPosition();
      setSidebarPosition((position) => {
        const followsRightDock =
          restingPosition !== null &&
          position.x >= window.innerWidth - MOBILE_BUBBLE_SIZE - MOBILE_EDGE_GAP - 24;
        const target = followsRightDock ? restingPosition : position;
        return clampSidebarPosition(target.x, target.y, size.width, size.height);
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [clampSidebarPosition, getMobileRestingPosition, getSidebarClampSize, router.asPath]);

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
    let frame: number | null = null;
    const updatePosition = () => {
      frame = null;
      const size = getSidebarClampSize();
      const restingPosition = getMobileRestingPosition();
      const textEntryFocused = isTextEntryElement(document.activeElement);
      if (textEntryFocused) setSidebarOpen(false);
      setSidebarPosition((pos) => {
        if (textEntryFocused) {
          if (!keyboardOriginRef.current) keyboardOriginRef.current = pos;
          const visualTop = window.visualViewport?.offsetTop || 0;
          return clampSidebarPosition(pos.x, Math.max(96, visualTop + 76), size.width, size.height);
        }
        if (keyboardOriginRef.current) {
          const origin = keyboardOriginRef.current;
          keyboardOriginRef.current = null;
          return clampSidebarPosition(origin.x, origin.y, size.width, size.height);
        }
        const followsRightDock =
          restingPosition !== null &&
          pos.x >= window.innerWidth - MOBILE_BUBBLE_SIZE - MOBILE_EDGE_GAP - 24;
        const target = followsRightDock ? restingPosition : pos;
        return clampSidebarPosition(target.x, target.y, size.width, size.height);
      });
    };
    const handler = () => {
      if (window.innerWidth > MOBILE_BREAKPOINT) return;
      if (frame !== null) return;
      frame = window.requestAnimationFrame(updatePosition);
    };
    const handleFocusOut = () => window.setTimeout(handler, 120);
    if (typeof window === 'undefined') return undefined;
    window.addEventListener('resize', handler);
    window.addEventListener('scroll', handler, { passive: true });
    window.addEventListener('focusin', handler);
    window.addEventListener('focusout', handleFocusOut);
    window.visualViewport?.addEventListener('resize', handler);
    window.visualViewport?.addEventListener('scroll', handler);
    return () => {
      window.removeEventListener('resize', handler);
      window.removeEventListener('scroll', handler);
      window.removeEventListener('focusin', handler);
      window.removeEventListener('focusout', handleFocusOut);
      window.visualViewport?.removeEventListener('resize', handler);
      window.visualViewport?.removeEventListener('scroll', handler);
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [clampSidebarPosition, getMobileRestingPosition, getSidebarClampSize]);


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
      const maxOffset = 5; // Keep both eyes clear of the circular edge while tracking.
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
      refreshSession();
    };
    window.addEventListener('floating-sidebar:toggle', handleOpen as EventListener);
    return () => window.removeEventListener('floating-sidebar:toggle', handleOpen as EventListener);
  }, [refreshSession]);

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

  if (router.pathname === '/login') return null;

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
