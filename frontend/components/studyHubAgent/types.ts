import { MaterialListItem } from '../../types/material';

export type StudyHubAgentRole = 'assistant' | 'user';

export type StudyHubAgentRecommendation = {
  materialId: number;
  title?: string;
  tags?: string[];
  reason?: string;
  summary?: string;
};

export type StudyHubAgentMessage = {
  id: string;
  role: StudyHubAgentRole;
  content: string;
  recommendations?: StudyHubAgentRecommendation[];
  followups?: string[];
};

export type StudyHubAgentMaterialDetails = Record<number, MaterialListItem>;

export type FloatingWidgetPosition = {
  left: number;
  top: number;
};
