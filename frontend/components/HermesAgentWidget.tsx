import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react';
import { fetchBackend } from '../lib/apiBase';
import { materialPath } from '../lib/slug';
import { MaterialListItem } from '../types/material';
import { SessionUser } from '../types/user';

type HermesRole = 'assistant' | 'user';

type HermesRecommendation = {
  materialId: number;
  title?: string;
  tags?: string[];
  reason?: string;
  summary?: string;
};

type HermesMessage = {
  id: string;
  role: HermesRole;
  content: string;
  recommendations?: HermesRecommendation[];
  followups?: string[];
};

type WidgetPosition = {
  left: number;
  top: number;
};

const STARTER_MESSAGES = [
  '两周后考通信原理，基础一般，怎么复习？',
  '帮我找数据结构链表相关资料',
  '高数下历年真题怎么刷更有效？',
];

const SESSION_STORAGE_KEY = 'hermes-agent-messages';
const POSITION_STORAGE_KEY = 'studyhub-agent-position';

const initialMessages: HermesMessage[] = [
  {
    id: 'welcome',
    role: 'assistant',
    content: '我是 StudyHub 学习辅导。你可以直接描述课程、考试时间、当前水平或卡住的题目，我会优先基于 StudyHub 平台资料给你推荐和规划。',
    followups: STARTER_MESSAGES,
  },
];

export default function HermesAgentWidget() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [user, setUser] = useState<SessionUser | null>(null);
  const [messages, setMessages] = useState<HermesMessage[]>(initialMessages);
  const [materialDetails, setMaterialDetails] = useState<Record<number, MaterialListItem>>({});
  const [position, setPosition] = useState<WidgetPosition | null>(null);
  const widgetRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const launcherPositionRef = useRef<WidgetPosition | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    offsetX: number;
    offsetY: number;
    dragging: boolean;
    startX: number;
    startY: number;
    source: 'launcher' | 'header';
    restorePosition: WidgetPosition | null;
    viewportOffsetX: number;
    viewportOffsetY: number;
  } | null>(null);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        setMessages(parsed);
      }
    } catch {
      // ignore invalid local state
    }
  }, []);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(POSITION_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (typeof parsed?.left === 'number' && typeof parsed?.top === 'number') {
        setPosition(constrainPosition(parsed.left, parsed.top, 176, 58));
      }
    } catch {
      // ignore invalid local state
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(messages.slice(-12)));
    } catch {
      // ignore storage errors
    }
  }, [messages]);

  useEffect(() => {
    if (!position) return;
    try {
      window.localStorage.setItem(POSITION_STORAGE_KEY, JSON.stringify(position));
    } catch {
      // ignore storage errors
    }
  }, [position]);

  useEffect(() => {
    if (!position || !widgetRef.current) return;
    const rect = widgetRef.current.getBoundingClientRect();
    const nextPosition = constrainPosition(position.left, position.top, rect.width, rect.height);
    if (nextPosition.left !== position.left || nextPosition.top !== position.top) {
      setPosition(nextPosition);
    }
  }, [open, position]);

  useEffect(() => {
    let active = true;
    const loadSession = async () => {
      try {
        const resp = await fetchBackend('/session');
        const json = await resp.json();
        if (!active) return;
        if (resp.ok && json?.ok && json.data?.user) {
          setUser(json.data.user);
        } else {
          setUser(null);
        }
      } catch {
        if (active) setUser(null);
      }
    };
    void loadSession();
    window.addEventListener('focus', loadSession);
    return () => {
      active = false;
      window.removeEventListener('focus', loadSession);
    };
  }, []);

  useEffect(() => {
    if (!open || !listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, open, loading]);

  const loadMaterialDetail = useCallback(
    async (materialId: number) => {
      if (materialDetails[materialId]) return;
      try {
        const resp = await fetchBackend(`/materials/${materialId}`);
        const json = await resp.json().catch(() => null);
        if (!resp.ok || !json?.ok || !json.data) return;
        setMaterialDetails((prev) => ({ ...prev, [materialId]: json.data }));
      } catch {
        // keep the recommendation card usable with title from AI output
      }
    },
    [materialDetails]
  );

  const submitQuery = useCallback(
    async (rawQuery: string) => {
      const query = rawQuery.trim();
      if (!query || loading) return;
      setInput('');
      setMessages((prev) => [...prev, { id: makeMessageId(), role: 'user', content: query }]);
      if (!user) {
        setMessages((prev) => [
          ...prev,
          {
            id: makeMessageId(),
            role: 'assistant',
            content: 'StudyHub 学习辅导需要登录后读取你的平台会话，才能基于平台资料给出推荐。请先登录后再试。',
          },
        ]);
        return;
      }
      setLoading(true);
      try {
        const resp = await fetchBackend('/ai-recommendations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query }),
        });
        const json = await resp.json().catch(() => null);
        if (!resp.ok || !json?.ok) {
          throw new Error(json?.msg || 'StudyHub 学习辅导暂时无法连接资料推荐服务');
        }
        const parsed = parseRecommendationOutput(json?.data?.output);
        const recommendations = normalizeRecommendations(parsed.recommendations);
        await Promise.all(recommendations.map((item) => loadMaterialDetail(item.materialId)));
        const answer = typeof parsed.answer === 'string' && parsed.answer.trim()
          ? parsed.answer.trim()
          : buildHermesAnswer(query, recommendations);
        setMessages((prev) => [
          ...prev,
          {
            id: makeMessageId(),
            role: 'assistant',
            content: answer,
            recommendations,
            followups: normalizeFollowups(parsed.followup_questions),
          },
        ]);
      } catch (error) {
        setMessages((prev) => [
          ...prev,
          {
            id: makeMessageId(),
            role: 'assistant',
            content: error instanceof Error ? error.message : 'StudyHub 学习辅导暂时无法回答，请稍后重试。',
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [loadMaterialDetail, loading, user]
  );

  const hasConversation = useMemo(() => messages.length > 1, [messages.length]);
  const widgetStyle = useMemo<CSSProperties | undefined>(() => {
    if (!position) return undefined;
    return {
      left: `${position.left}px`,
      top: `${position.top}px`,
      right: 'auto',
      bottom: 'auto',
    };
  }, [position]);

  const startDrag = useCallback((event: ReactPointerEvent<HTMLElement>, source: 'launcher' | 'header') => {
    if (event.button !== 0 || !widgetRef.current) return;
    const widgetRect = widgetRef.current.getBoundingClientRect();
    const handleRect = event.currentTarget.getBoundingClientRect();
    const widgetStyle = getComputedStyle(widgetRef.current);
    const viewportOffsetX = widgetRect.left - (Number.parseFloat(widgetStyle.left) || widgetRect.left);
    const viewportOffsetY = widgetRect.top - (Number.parseFloat(widgetStyle.top) || widgetRect.top);
    dragRef.current = {
      pointerId: event.pointerId,
      offsetX: event.clientX - widgetRect.left,
      offsetY: event.clientY - widgetRect.top,
      dragging: false,
      startX: event.clientX,
      startY: event.clientY,
      source,
      restorePosition: source === 'launcher' ? { left: handleRect.left - viewportOffsetX, top: handleRect.top - viewportOffsetY } : null,
      viewportOffsetX,
      viewportOffsetY,
    };
    widgetRef.current.setPointerCapture(event.pointerId);
  }, []);

  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !widgetRef.current) return;
    const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (distance <= 6 && !drag.dragging) return;
    if (!drag.dragging) {
      drag.dragging = true;
    }
    const rect = widgetRef.current.getBoundingClientRect();
    setPosition(
      constrainPosition(
        event.clientX - drag.offsetX - drag.viewportOffsetX,
        event.clientY - drag.offsetY - drag.viewportOffsetY,
        rect.width,
        rect.height
      )
    );
  }, []);

  const finishDrag = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !widgetRef.current) return;
    if (widgetRef.current.hasPointerCapture(event.pointerId)) {
      widgetRef.current.releasePointerCapture(event.pointerId);
    }
    if (drag.source === 'launcher' && !drag.dragging) {
      launcherPositionRef.current = drag.restorePosition;
      setOpen(true);
    }
    dragRef.current = null;
  }, []);

  return (
    <section
      ref={widgetRef}
      className={`hermes-agent ${open ? 'is-open' : ''}`}
      style={widgetStyle}
      aria-label="StudyHub 学习辅导"
      onPointerMove={handlePointerMove}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
    >
      {!open ? (
        <button
          className="hermes-agent__launcher"
          type="button"
          onPointerDown={(event) => startDrag(event, 'launcher')}
        >
          <span className="hermes-agent__spark" aria-hidden="true" />
          <span>
            <strong>StudyHub</strong>
            <small>学习辅导</small>
          </span>
        </button>
      ) : (
        <div className="hermes-agent__panel">
          <div className="hermes-agent__header" onPointerDown={(event) => startDrag(event, 'header')}>
            <div>
              <span className="hermes-agent__eyebrow">StudyHub Agent</span>
              <h3>StudyHub 学习辅导</h3>
            </div>
            <button
              className="hermes-agent__close"
              type="button"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                const restorePosition = launcherPositionRef.current;
                setOpen(false);
                if (restorePosition) {
                  window.requestAnimationFrame(() => setPosition(restorePosition));
                }
              }}
              aria-label="收起 StudyHub 学习辅导"
            >
              ×
            </button>
          </div>
          <div className="hermes-agent__status">
            <span className={user ? 'is-online' : 'is-offline'} />
            {user ? '已连接平台资料库' : '登录后可基于平台资料对话'}
          </div>
          <div className="hermes-agent__messages" ref={listRef}>
            {messages.map((message) => (
              <article key={message.id} className={`hermes-agent__message hermes-agent__message--${message.role}`}>
                <p>{message.content}</p>
                {message.recommendations && message.recommendations.length > 0 && (
                  <div className="hermes-agent__materials">
                    {message.recommendations.map((item) => {
                      const detail = materialDetails[item.materialId];
                      const title = detail?.title || item.title || `资料 #${item.materialId}`;
                      const tags = detail?.tags || item.tags || [];
                      return (
                        <Link
                          key={item.materialId}
                          className="hermes-agent__material"
                          href={materialPath(item.materialId, title)}
                        >
                          <strong>{title}</strong>
                          <span>{item.reason || item.summary || '来自 StudyHub 资料库的候选内容'}</span>
                          {tags.length > 0 && (
                            <em>{tags.slice(0, 3).join(' / ')}</em>
                          )}
                        </Link>
                      );
                    })}
                  </div>
                )}
                {message.followups && message.followups.length > 0 && (
                  <div className="hermes-agent__followups">
                    {message.followups.slice(0, 3).map((item) => (
                      <button key={item} type="button" onClick={() => void submitQuery(item)}>
                        {item}
                      </button>
                    ))}
                  </div>
                )}
              </article>
            ))}
            {loading && (
              <article className="hermes-agent__message hermes-agent__message--assistant">
                <p>StudyHub 正在检索平台资料...</p>
              </article>
            )}
          </div>
          {!hasConversation && (
            <div className="hermes-agent__starters">
              {STARTER_MESSAGES.map((item) => (
                <button key={item} type="button" onClick={() => void submitQuery(item)}>
                  {item}
                </button>
              ))}
            </div>
          )}
          <form
            className="hermes-agent__form"
            onSubmit={(event) => {
              event.preventDefault();
              void submitQuery(input);
            }}
          >
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="描述你要学什么、多久考试、哪里卡住"
              disabled={loading}
            />
            <button type="submit" disabled={loading || !input.trim()}>
              发送
            </button>
          </form>
        </div>
      )}
    </section>
  );
}

function parseRecommendationOutput(output: unknown): Record<string, unknown> {
  if (typeof output !== 'string') return {};
  const start = output.indexOf('<json>');
  const end = output.indexOf('</json>');
  const body = start >= 0 && end > start ? output.slice(start + 6, end).trim() : output.trim();
  try {
    const parsed = JSON.parse(body);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function normalizeRecommendations(value: unknown): HermesRecommendation[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item): HermesRecommendation | null => {
      if (!item || typeof item !== 'object') return null;
      const record = item as Record<string, unknown>;
      const materialId = Number(record.material_id ?? record.materialId ?? record.id);
      if (!Number.isFinite(materialId)) return null;
      return {
        materialId,
        title: typeof record.title === 'string' ? record.title : undefined,
        tags: Array.isArray(record.tags) ? record.tags.filter((tag): tag is string => typeof tag === 'string') : undefined,
        reason: pickText(record.reason, record.explain, record.match_reason, record.note),
        summary: typeof record.summary === 'string' ? record.summary : undefined,
      };
    })
    .filter((item): item is HermesRecommendation => Boolean(item))
    .slice(0, 3);
}

function normalizeFollowups(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).slice(0, 3);
}

function pickText(...values: unknown[]) {
  return values.find((value): value is string => typeof value === 'string' && value.trim().length > 0);
}

function buildHermesAnswer(query: string, recommendations: HermesRecommendation[]) {
  if (recommendations.length === 0) {
    return `我没有在平台资料库里找到足够贴近「${query}」的候选。你可以补充课程名、考试范围、题型或学校专业，我再帮你缩小检索。`;
  }
  const titles = recommendations.map((item) => `《${item.title || `资料 #${item.materialId}`}》`).join('、');
  return `我先基于 StudyHub 资料库找到 ${titles}。建议先用最匹配的资料建立知识框架，再结合真题或经验内容做查漏补缺；如果你告诉我考试时间和基础水平，我可以继续帮你拆成复习步骤。`;
}

function constrainPosition(left: number, top: number, width: number, height: number): WidgetPosition {
  if (typeof window === 'undefined') {
    return { left, top };
  }
  const margin = 12;
  const maxLeft = Math.max(margin, window.innerWidth - width - margin);
  const maxTop = Math.max(margin, window.innerHeight - height - margin);
  return {
    left: Math.min(Math.max(left, margin), maxLeft),
    top: Math.min(Math.max(top, margin), maxTop),
  };
}

function makeMessageId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
