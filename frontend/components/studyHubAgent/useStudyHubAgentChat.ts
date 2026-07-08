import { useCallback, useEffect, useState } from 'react';
import { fetchOptionalSessionUser } from '../../lib/sessionApi';
import {
  fetchStudyHubAgentMaterial,
  requestStudyHubAgentRecommendations,
  requestStudyHubAgentRecommendationsStream,
} from '../../lib/studyHubAgentApi';
import { SessionUser } from '../../types/user';
import { STUDYHUB_AGENT_INITIAL_MESSAGES, STUDYHUB_AGENT_MESSAGES_STORAGE_KEY } from './constants';
import {
  StudyHubAgentImageAttachment,
  StudyHubAgentMaterialDetails,
  StudyHubAgentMessage,
  StudyHubAgentRecommendation,
} from './types';

const STORED_CONTEXT_MESSAGE_LIMIT = 24;
const RECENT_CONTEXT_MESSAGE_LIMIT = 8;
const EARLIER_CONTEXT_MESSAGE_SCAN_LIMIT = 16;
const CONTEXT_QUERY_MAX_CHARS = 1000;
const CONTEXT_LINE_MAX_CHARS = 220;
const EARLIER_CONTEXT_SUMMARY_MAX_CHARS = 360;
const IMAGE_ONLY_QUERY = '请根据这张图片帮我分析学习问题';

const COURSE_CONTEXT_HINTS: { label: string; aliases: string[] }[] = [
  { label: '电子系统设计', aliases: ['电子系统设计', 'ESD'] },
  { label: '通信原理', aliases: ['通信原理', 'CPS'] },
  { label: '信号与系统', aliases: ['信号与系统', 'signals', 'signal'] },
  { label: '数据结构', aliases: ['数据结构'] },
  { label: '高等数学', aliases: ['高等数学', '高数', '微积分'] },
  { label: '概率论', aliases: ['概率论'] },
];

export const useStudyHubAgentChat = () => {
  const [loading, setLoading] = useState(false);
  const [thinkingStages, setThinkingStages] = useState<string[]>([]);
  const [user, setUser] = useState<SessionUser | null>(null);
  const [messages, setMessages] = useState<StudyHubAgentMessage[]>(STUDYHUB_AGENT_INITIAL_MESSAGES);
  const [materialDetails, setMaterialDetails] = useState<StudyHubAgentMaterialDetails>({});

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STUDYHUB_AGENT_MESSAGES_STORAGE_KEY);
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
      window.localStorage.setItem(
        STUDYHUB_AGENT_MESSAGES_STORAGE_KEY,
        JSON.stringify(serializeMessagesForStorage(messages.slice(-STORED_CONTEXT_MESSAGE_LIMIT)))
      );
    } catch {
      // ignore storage errors
    }
  }, [messages]);

  useEffect(() => {
    let active = true;
    const loadSession = async () => {
      const nextUser = await fetchOptionalSessionUser();
      if (active) setUser(nextUser);
    };
    void loadSession();
    window.addEventListener('focus', loadSession);
    return () => {
      active = false;
      window.removeEventListener('focus', loadSession);
    };
  }, []);

  const loadMaterialDetail = useCallback(
    async (materialId: number) => {
      if (materialDetails[materialId]) return;
      try {
        const detail = await fetchStudyHubAgentMaterial(materialId);
        setMaterialDetails((prev) => ({ ...prev, [materialId]: detail }));
      } catch {
        // keep the recommendation card usable with title from AI output
      }
    },
    [materialDetails]
  );

  const submitQuery = useCallback(
    async (rawQuery: string, imageAttachments: StudyHubAgentImageAttachment[] = []) => {
      const query = rawQuery.trim() || (imageAttachments.length > 0 ? IMAGE_ONLY_QUERY : '');
      const attachments = imageAttachments.slice(0, 1);
      if ((!query && attachments.length === 0) || loading) return;
      setMessages((prev) => [
        ...prev,
        { id: makeMessageId(), role: 'user', content: query, imageAttachments: attachments },
      ]);
      if (!user) {
        setMessages((prev) => [
          ...prev,
          {
            id: makeMessageId(),
            role: 'assistant',
            content:
              'StudyHub 学习辅导需要登录后读取你的平台会话，才能基于平台资料给出推荐。请先登录后再试。',
          },
        ]);
        return;
      }
      setLoading(true);
      setThinkingStages(['理解问题中']);
      try {
        const contextQuery = buildStudyHubAgentContext(messages, query);
        const data = await requestStudyHubAgentRecommendationsStream(
          query,
          contextQuery,
          attachments,
          {
            onStage: (stage) => {
              setThinkingStages((prev) => appendThinkingStage(prev, stage));
            },
          }
        ).catch(async () => {
          setThinkingStages((prev) => appendThinkingStage(prev, '降级到普通请求'));
          return requestStudyHubAgentRecommendations(query, contextQuery, attachments);
        });
        const parsed = parseRecommendationOutput(data.output);
        const recommendations = normalizeRecommendations(parsed.recommendations);
        await Promise.all(recommendations.map((item) => loadMaterialDetail(item.materialId)));
        const answer =
          typeof parsed.answer === 'string' && parsed.answer.trim()
            ? parsed.answer.trim()
            : buildStudyHubAgentAnswer(query, recommendations);
        setMessages((prev) => [
          ...prev,
          {
            id: makeMessageId(),
            role: 'assistant',
            content: answer,
            recommendations,
            followups: normalizeFollowups(parsed.followup_questions, query),
          },
        ]);
      } catch (error) {
        setMessages((prev) => [
          ...prev,
          {
            id: makeMessageId(),
            role: 'assistant',
            content:
              error instanceof Error
                ? error.message
                : 'StudyHub 学习辅导暂时无法回答，请稍后重试。',
          },
        ]);
      } finally {
        setLoading(false);
        setThinkingStages([]);
      }
    },
    [loadMaterialDetail, loading, messages, user]
  );

  return {
    loading,
    thinkingStages,
    user,
    messages,
    materialDetails,
    submitQuery,
  };
};

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

function normalizeRecommendations(value: unknown): StudyHubAgentRecommendation[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item): StudyHubAgentRecommendation | null => {
      if (!item || typeof item !== 'object') return null;
      const record = item as Record<string, unknown>;
      const materialId = Number(record.material_id ?? record.materialId ?? record.id);
      if (!Number.isFinite(materialId)) return null;
      return {
        materialId,
        title: typeof record.title === 'string' ? record.title : undefined,
        tags: Array.isArray(record.tags)
          ? record.tags.filter((tag): tag is string => typeof tag === 'string')
          : undefined,
        reason: pickText(record.reason, record.explain, record.match_reason, record.note),
        summary: typeof record.summary === 'string' ? record.summary : undefined,
      };
    })
    .filter((item): item is StudyHubAgentRecommendation => Boolean(item))
    .slice(0, 3);
}

export function normalizeFollowups(value: unknown, currentQuery = ''): string[] {
  if (!Array.isArray(value)) return [];
  const currentKey = followupKey(currentQuery);
  const seen = new Set<string>();
  return value
    .map((item) => (typeof item === 'string' ? normalizeFollowupVoice(item) : ''))
    .filter((item): item is string => {
      if (!item) return false;
      const key = followupKey(item);
      if (!key || key === currentKey || seen.has(key)) return false;
      if (isBadFollowupPrompt(item)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 3);
}

function serializeMessagesForStorage(messages: StudyHubAgentMessage[]) {
  return messages.map((message) => ({
    ...message,
    imageAttachments: message.imageAttachments?.map((item) => ({
      id: item.id,
      name: item.name,
      mimeType: item.mimeType,
      sizeBytes: item.sizeBytes,
    })),
  }));
}

function pickText(...values: unknown[]) {
  return values.find(
    (value): value is string => typeof value === 'string' && value.trim().length > 0
  );
}

function appendThinkingStage(stages: string[], stage: string) {
  const cleaned = stage.trim();
  if (!cleaned) return stages;
  if (stages.includes(cleaned)) return stages;
  return [...stages, cleaned].slice(-6);
}

function followupKey(value: string) {
  return value.replace(/[^\u4e00-\u9fa5A-Za-z0-9]+/g, '').toLowerCase();
}

function isBadFollowupPrompt(value: string) {
  const normalized = followupKey(value);
  return [
    '你的考试日期和每天可复习时间',
    '我的考试日期和每天可复习时间是',
    '考试日期和每天可复习时间是',
    '告诉我考试时间',
    '请补充课程名',
    '需要我',
    '我可以帮你',
    '是否想',
    '是否希望',
    '你是否想',
    '你想不想',
  ].some((marker) => normalized.includes(marker));
}

function normalizeFollowupVoice(value: string) {
  let text = value.trim().replace(/\s+/g, ' ').replace(/[?？。]+$/g, '');
  const replacements: Array<[string, string]> = [
    ['需要我帮你', ''],
    ['需要我', ''],
    ['我可以帮你', ''],
    ['是否想', ''],
    ['你是否想', ''],
    ['想不想', ''],
    ['你想不想', ''],
    ['是否希望我', ''],
    ['你希望我', ''],
    ['要不要我帮你', ''],
    ['要不要我', ''],
    ['是否需要我', ''],
    ['是否需要', ''],
  ];
  for (const [from, to] of replacements) {
    if (text.startsWith(from)) {
      text = `${to}${text.slice(from.length)}`.trim();
      break;
    }
  }
  text = text.replace(/你的/g, '我的').replace(/帮你/g, '帮我').replace(/吗$/g, '');
  return text.trim();
}

function buildStudyHubAgentAnswer(query: string, recommendations: StudyHubAgentRecommendation[]) {
  if (recommendations.length === 0) {
    return `我没有在平台资料库里找到足够贴近「${query}」的候选。你可以补充课程名、考试范围、题型或学校专业，我再帮你缩小检索。`;
  }
  const titles = recommendations
    .map((item) => `《${item.title || `资料 #${item.materialId}`}》`)
    .join('、');
  return `我先基于 StudyHub 资料库找到 ${titles}。建议先用最匹配的资料建立知识框架，再结合真题或经验内容做查漏补缺；如果你告诉我考试时间和基础水平，我可以继续帮你拆成复习步骤。`;
}

export function buildStudyHubAgentContext(messages: StudyHubAgentMessage[], query: string) {
  const currentQuery = query.trim();
  const contextMessages = messages
    .filter((message) => message.content.trim() && message.content.trim() !== currentQuery)
    .slice(-STORED_CONTEXT_MESSAGE_LIMIT);
  const recentMessages = contextMessages.slice(-RECENT_CONTEXT_MESSAGE_LIMIT);
  const earlierMessages = contextMessages.slice(
    0,
    Math.max(0, contextMessages.length - recentMessages.length)
  );
  const earlierSummary = buildStudyHubAgentEarlierContextSummary(earlierMessages);
  const recentContext = recentMessages
    .map(formatStudyHubAgentContextLine)
    .filter(Boolean)
    .join('\n');

  if (!earlierSummary) {
    return recentContext.slice(-CONTEXT_QUERY_MAX_CHARS);
  }
  const recentBudget = Math.max(0, CONTEXT_QUERY_MAX_CHARS - earlierSummary.length - 1);
  const trimmedRecentContext = recentContext.slice(-recentBudget);
  return [earlierSummary, trimmedRecentContext]
    .filter(Boolean)
    .join('\n')
    .slice(0, CONTEXT_QUERY_MAX_CHARS);
}

function redactStudyHubAgentContextText(value: string) {
  return value
    .replace(/https?:\/\/[^\s,;，；。]+|www\.[^\s,;，；。]+/gi, '[redacted-url]')
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[redacted-email]')
    .replace(/(^|[^\d])(1[3-9]\d{9})(?!\d)/g, '$1[redacted-phone]')
    .replace(
      /(api[_-]?key|token|secret|authorization|bearer)\s*[:=]\s*[^\s,;，；。]+/gi,
      '[redacted-secret]'
    );
}

function formatStudyHubAgentContextLine(message: StudyHubAgentMessage) {
  const role = message.role === 'user' ? '用户' : '助手';
  const content = redactStudyHubAgentContextText(message.content).slice(0, CONTEXT_LINE_MAX_CHARS);
  const titles = collectRecommendationTitles([message], 3);
  const imageHint = collectImageAttachmentHints([message], 2);
  const titleHint = titles.length > 0 ? ` 推荐资料：${titles.join('；')}` : '';
  const attachmentHint = imageHint.length > 0 ? ` 图片：${imageHint.join('；')}` : '';
  return `${role}：${content}${titleHint}${attachmentHint}`;
}

function buildStudyHubAgentEarlierContextSummary(messages: StudyHubAgentMessage[]) {
  if (messages.length === 0) return '';
  const scannedMessages = messages.slice(-EARLIER_CONTEXT_MESSAGE_SCAN_LIMIT);
  const courseHints = collectCourseHints(scannedMessages);
  const titles = collectRecommendationTitles(scannedMessages, 4);
  const userGoals = scannedMessages
    .filter((message) => message.role === 'user')
    .map((message) => redactStudyHubAgentContextText(message.content).trim())
    .filter((content) => content.length >= 2)
    .slice(-2);

  const parts: string[] = [];
  if (courseHints.length > 0) {
    parts.push(`课程/关键词：${courseHints.join('、')}`);
  }
  if (titles.length > 0) {
    parts.push(`曾推荐资料：${titles.join('；')}`);
  }
  if (userGoals.length > 0) {
    parts.push(`早期用户目标：${userGoals.join('；')}`);
  }
  if (parts.length === 0) return '';
  return `早期上下文摘要：${parts.join('。')}`.slice(0, EARLIER_CONTEXT_SUMMARY_MAX_CHARS);
}

function collectCourseHints(messages: StudyHubAgentMessage[]) {
  const haystack = messages
    .flatMap((message) => [
      message.content,
      ...(message.recommendations || []).flatMap((item) => [
        item.title || '',
        item.summary || '',
        ...(item.tags || []),
      ]),
    ])
    .map(redactStudyHubAgentContextText)
    .join(' ');
  const normalizedHaystack = haystack.toLowerCase();
  const hints: string[] = [];
  COURSE_CONTEXT_HINTS.forEach((item) => {
    if (item.aliases.some((alias) => normalizedHaystack.includes(alias.toLowerCase()))) {
      hints.push(item.label);
    }
  });
  return hints.slice(0, 4);
}

function collectRecommendationTitles(messages: StudyHubAgentMessage[], limit: number) {
  const titles: string[] = [];
  messages.forEach((message) => {
    (message.recommendations || []).forEach((item) => {
      const title = item.title ? redactStudyHubAgentContextText(item.title).trim() : '';
      if (title && !titles.includes(title)) {
        titles.push(title);
      }
    });
  });
  return titles.slice(-limit);
}

function collectImageAttachmentHints(messages: StudyHubAgentMessage[], limit: number) {
  const hints: string[] = [];
  messages.forEach((message) => {
    (message.imageAttachments || []).forEach((item) => {
      const name = redactStudyHubAgentContextText(item.name || '学习图片').trim();
      const hint = `${name || '学习图片'}(${item.mimeType}, ${item.sizeBytes}B)`;
      if (!hints.includes(hint)) {
        hints.push(hint);
      }
    });
  });
  return hints.slice(-limit);
}

function makeMessageId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
