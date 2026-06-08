import { useCallback, useEffect, useState } from 'react';
import { fetchOptionalSessionUser } from '../../lib/sessionApi';
import { fetchStudyHubAgentMaterial, requestStudyHubAgentRecommendations } from '../../lib/studyHubAgentApi';
import { SessionUser } from '../../types/user';
import {
  STUDYHUB_AGENT_INITIAL_MESSAGES,
  STUDYHUB_AGENT_MESSAGES_STORAGE_KEY,
} from './constants';
import {
  StudyHubAgentMaterialDetails,
  StudyHubAgentMessage,
  StudyHubAgentRecommendation,
} from './types';

export const useStudyHubAgentChat = () => {
  const [loading, setLoading] = useState(false);
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
      window.localStorage.setItem(STUDYHUB_AGENT_MESSAGES_STORAGE_KEY, JSON.stringify(messages.slice(-12)));
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
    async (rawQuery: string) => {
      const query = rawQuery.trim();
      if (!query || loading) return;
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
        const contextQuery = buildStudyHubAgentContext(messages, query);
        const data = await requestStudyHubAgentRecommendations(query, contextQuery);
        const parsed = parseRecommendationOutput(data.output);
        const recommendations = normalizeRecommendations(parsed.recommendations);
        await Promise.all(recommendations.map((item) => loadMaterialDetail(item.materialId)));
        const answer = typeof parsed.answer === 'string' && parsed.answer.trim()
          ? parsed.answer.trim()
          : buildStudyHubAgentAnswer(query, recommendations);
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
    [loadMaterialDetail, loading, messages, user]
  );

  return {
    loading,
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
        tags: Array.isArray(record.tags) ? record.tags.filter((tag): tag is string => typeof tag === 'string') : undefined,
        reason: pickText(record.reason, record.explain, record.match_reason, record.note),
        summary: typeof record.summary === 'string' ? record.summary : undefined,
      };
    })
    .filter((item): item is StudyHubAgentRecommendation => Boolean(item))
    .slice(0, 3);
}

function normalizeFollowups(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).slice(0, 3);
}

function pickText(...values: unknown[]) {
  return values.find((value): value is string => typeof value === 'string' && value.trim().length > 0);
}

function buildStudyHubAgentAnswer(query: string, recommendations: StudyHubAgentRecommendation[]) {
  if (recommendations.length === 0) {
    return `我没有在平台资料库里找到足够贴近「${query}」的候选。你可以补充课程名、考试范围、题型或学校专业，我再帮你缩小检索。`;
  }
  const titles = recommendations.map((item) => `《${item.title || `资料 #${item.materialId}`}》`).join('、');
  return `我先基于 StudyHub 资料库找到 ${titles}。建议先用最匹配的资料建立知识框架，再结合真题或经验内容做查漏补缺；如果你告诉我考试时间和基础水平，我可以继续帮你拆成复习步骤。`;
}

function buildStudyHubAgentContext(messages: StudyHubAgentMessage[], query: string) {
  const currentQuery = query.trim();
  const lines = messages
    .filter((message) => message.content.trim() && message.content.trim() !== currentQuery)
    .slice(-8)
    .map((message) => {
      const role = message.role === 'user' ? '用户' : '助手';
      const content = redactStudyHubAgentContextText(message.content).slice(0, 220);
      const titles = (message.recommendations || [])
        .map((item) => (item.title ? redactStudyHubAgentContextText(item.title) : undefined))
        .filter((title): title is string => Boolean(title && title.trim()))
        .slice(0, 3);
      const titleHint = titles.length > 0 ? ` 推荐资料：${titles.join('；')}` : '';
      return `${role}：${content}${titleHint}`;
    })
    .filter((line) => line.trim().length > 0);
  return lines.join('\n').slice(-1000);
}

function redactStudyHubAgentContextText(value: string) {
  return value
    .replace(/https?:\/\/[^\s,;，；。]+|www\.[^\s,;，；。]+/gi, '[redacted-url]')
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[redacted-email]')
    .replace(/(^|[^\d])(1[3-9]\d{9})(?!\d)/g, '$1[redacted-phone]')
    .replace(/(api[_-]?key|token|secret|authorization|bearer)\s*[:=]\s*[^\s,;，；。]+/gi, '[redacted-secret]');
}

function makeMessageId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
