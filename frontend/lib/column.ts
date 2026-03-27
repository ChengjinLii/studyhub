export const COLUMN_TOPIC_TITLES = {
  experience: '经验心得',
  leetcode: 'LeetCode 解析',
  llm: 'LLM 入门',
  'grad-school': '保研面经',
  career: '求职面经',
  'postgrad-exam': '考研攻略',
  overseas: '留学指南',
} as const;

export const COLUMN_TOPIC_TAGS = {
  experience: '经验分享',
  leetcode: 'LeetCode解析',
  llm: 'LLM入门',
  'grad-school': '保研面经',
  career: '求职面经',
  'postgrad-exam': '考研攻略',
  overseas: '留学指南',
} as const;

export const COMMUNITY_COLUMN_TOPICS = ['experience', 'grad-school', 'career', 'postgrad-exam', 'overseas'] as const;

export type ColumnTopicKey = keyof typeof COLUMN_TOPIC_TITLES;

export const normalizeColumnTopic = (value: unknown): ColumnTopicKey => {
  if (typeof value !== 'string') return 'experience';
  return value in COLUMN_TOPIC_TITLES ? (value as ColumnTopicKey) : 'experience';
};

export const getColumnTopicTitle = (topic: ColumnTopicKey) => COLUMN_TOPIC_TITLES[topic];

export const getColumnTopicExtraTag = (topic: ColumnTopicKey) =>
  topic === 'experience' ? null : COLUMN_TOPIC_TAGS[topic];

export const isCommunityColumnTopic = (topic: ColumnTopicKey) =>
  COMMUNITY_COLUMN_TOPICS.includes(topic as (typeof COMMUNITY_COLUMN_TOPICS)[number]);

export const resolveExperienceTopicFromTags = (tags: string[] = []): ColumnTopicKey => {
  if (tags.includes(COLUMN_TOPIC_TAGS['grad-school'])) return 'grad-school';
  if (tags.includes(COLUMN_TOPIC_TAGS.career)) return 'career';
  if (tags.includes(COLUMN_TOPIC_TAGS['postgrad-exam']) || tags.includes('考研心得')) return 'postgrad-exam';
  if (tags.includes(COLUMN_TOPIC_TAGS.overseas) || tags.includes('留学心得')) return 'overseas';
  if (tags.includes(COLUMN_TOPIC_TAGS.leetcode)) return 'leetcode';
  if (tags.includes(COLUMN_TOPIC_TAGS.llm)) return 'llm';
  return 'experience';
};

export const buildExperienceUploadPath = (topic: ColumnTopicKey) => `/upload?topic=${encodeURIComponent(topic)}`;
