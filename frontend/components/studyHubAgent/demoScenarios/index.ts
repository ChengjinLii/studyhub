import { StudyHubAgentMessage } from '../types';
import { STUDY_PLAN_DEMO_SCENARIOS, inferScenarioFromContext } from './studyPlans';
import { StudyHubAgentDemoTurn } from './types';

const DEMO_SCENARIOS_ENABLED = process.env.NEXT_PUBLIC_STUDYHUB_AGENT_DEMO_SCENARIOS !== 'false';

export function resolveStudyHubAgentDemoTurn(
  query: string,
  messages: StudyHubAgentMessage[]
): StudyHubAgentDemoTurn | null {
  if (!DEMO_SCENARIOS_ENABLED) return null;
  const scenario = inferScenarioFromContext(STUDY_PLAN_DEMO_SCENARIOS, query, messages);
  if (!scenario) return null;
  return scenario.resolve(query, messages);
}

export type { StudyHubAgentDemoTurn } from './types';
