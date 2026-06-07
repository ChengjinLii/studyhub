import { StudyHubAgentMessage } from './types';

export const STUDYHUB_AGENT_STARTERS = [
  '两周后考通信原理，基础一般，怎么复习？',
  '帮我找数据结构链表相关资料',
  '高数下历年真题怎么刷更有效？',
];

export const STUDYHUB_AGENT_MESSAGES_STORAGE_KEY = 'hermes-agent-messages';
export const STUDYHUB_AGENT_POSITION_STORAGE_KEY = 'studyhub-agent-position';

export const STUDYHUB_AGENT_INITIAL_MESSAGES: StudyHubAgentMessage[] = [
  {
    id: 'welcome',
    role: 'assistant',
    content: '我是 StudyHub 学习辅导。你可以直接描述课程、考试时间、当前水平或卡住的题目，我会优先基于 StudyHub 平台资料给你推荐和规划。',
    followups: STUDYHUB_AGENT_STARTERS,
  },
];
