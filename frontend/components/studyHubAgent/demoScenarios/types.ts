import { StudyHubAgentMessage, StudyHubAgentRecommendation } from '../types';

export type StudyHubAgentDemoTurn = {
  answer: string;
  followups: string[];
  recommendations: StudyHubAgentRecommendation[];
  stage?: string;
};

export type StudyHubAgentDemoScenario = {
  id: string;
  courseNames: string[];
  aliases: string[];
  recommendations: StudyHubAgentRecommendation[];
  resolve: (query: string, messages: StudyHubAgentMessage[]) => StudyHubAgentDemoTurn | null;
};
