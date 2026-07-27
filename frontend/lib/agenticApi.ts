import { buildBackendUrl, fetchBackend } from './apiBase';
import { unwrapApiResponse } from './apiEnvelope';

export type AgentRunStatus =
  | 'created'
  | 'queued'
  | 'running'
  | 'waiting'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface AgentEvent {
  id: string;
  sequence: number;
  name: string;
  payload: Record<string, unknown>;
  occurredAt: string | null;
}

export interface AgentStep {
  id: string;
  index: number;
  node: string;
  planStepId: string | null;
  subagent: string | null;
  status: string;
  actionType: string | null;
  skillName: string | null;
  observationRef: string | null;
  artifactRefs: unknown[];
  stateBeforeHash: string | null;
  stateAfterHash: string | null;
  stateAbstractKey: string | null;
  stateGroupKeyV2: string | null;
  errorCode: string | null;
  startedAt: string | null;
  completedAt: string | null;
}

export interface AgentWait {
  id: string;
  stepId: string | null;
  type: string;
  status: string;
  request: Record<string, unknown>;
  expiresAt: string | null;
  resolvedAt: string | null;
  createdAt: string | null;
  resumeToken?: string;
}

export interface AgentArtifact {
  id: string;
  threadId: string;
  runId: string | null;
  artifactType: string;
  artifactKey: string;
  version: number;
  schemaVersion: string;
  contentHash: string | null;
  externalUri: string | null;
  mediaType: string | null;
  contentSizeBytes: number | null;
  trainingAllowed: boolean;
  sensitivity: string;
  licenseClass: string;
  sourceScope: string;
  containsPersonalData: boolean;
  anonymizationVersion: string | null;
  retentionPolicy: string;
  preview: unknown;
  createdAt: string | null;
}

export interface AgentJob {
  id: string;
  type: string;
  status: string;
  attempts: number;
  maxAttempts: number;
  errorCode: string | null;
  scheduledAt: string | null;
  claimedAt: string | null;
  completedAt: string | null;
  createdAt: string | null;
}

export interface AgentObservability {
  plan: Array<{ planStepId: string | null; node: string; status: string; actionType: string | null }>;
  steps: number;
  searchQueries: Array<{ sequence: number; query: string; name: string }>;
  tools: Array<{ stepId: string; skillName: string; status: string }>;
  evidenceGraph: { artifactCount: number; nodes: unknown[]; edges: unknown[]; available: boolean };
  contextCompression: Array<{ sequence: number; payload: Record<string, unknown> }>;
  verifier: Array<{ sequence: number; name: string; payload: Record<string, unknown> }>;
  usage: { inputTokens: number; outputTokens: number; totalTokens: number; cost: number; available: boolean };
  latencyMs: Record<string, number>;
}

export interface AgentRun {
  id: string;
  threadId: string;
  adminActorId: number;
  status: AgentRunStatus;
  runKind: 'agent_run' | 'deep_research' | string;
  goal: string | null;
  successCriteria: string[];
  shadowMode: boolean;
  trigger: { type: string; ref: string | null };
  runtime: { version: string; policyVersion: string };
  environmentSnapshotId: string;
  currentStepId: string | null;
  checkpointRef: string | null;
  stateHash: string | null;
  terminalReason: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  startedAt: string | null;
  completedAt: string | null;
  canResume: boolean;
  canCancel: boolean;
  latestEventSequence: number;
  steps?: AgentStep[];
  waits?: AgentWait[];
  artifacts?: AgentArtifact[];
  jobs?: AgentJob[];
  events?: AgentEvent[];
  observability?: AgentObservability;
}

export interface AgentRunList {
  items: AgentRun[];
  meta: { limit: number; total: number };
}

export interface AgentArtifactList {
  items: AgentArtifact[];
  meta: { limit: number; total: number };
}

const withQuery = (path: string, params: Record<string, string | number | undefined>) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') search.set(key, String(value));
  });
  const rendered = search.toString();
  return rendered ? `${path}?${rendered}` : path;
};

export const fetchAdminAgentRuns = async (params: { limit?: number; status?: string } = {}) => {
  const response = await fetchBackend(withQuery('/admin/agent-runs', params));
  return unwrapApiResponse<AgentRunList>(response, '加载 Agent 运行记录失败');
};

export const fetchAdminAgentRunsForSsr = async (token: string, origin?: string) => {
  const response = await fetchBackend('/admin/agent-runs', { headers: { Authorization: `Bearer ${token}` } }, origin);
  return unwrapApiResponse<AgentRunList>(response, '加载 Agent 运行记录失败');
};

export const fetchAdminAgentRun = async (runId: string) => {
  const response = await fetchBackend(`/admin/agent-runs/${encodeURIComponent(runId)}`);
  return unwrapApiResponse<AgentRun>(response, '加载 Agent 运行详情失败');
};

export const fetchAdminAgentRunForSsr = async (runId: string, token: string, origin?: string) => {
  const response = await fetchBackend(
    `/admin/agent-runs/${encodeURIComponent(runId)}`,
    { headers: { Authorization: `Bearer ${token}` } },
    origin
  );
  return unwrapApiResponse<AgentRun>(response, '加载 Agent 运行详情失败');
};

export const createAdminAgentRun = async (payload: {
  goal: string;
  title?: string;
  successCriteria?: string[];
  idempotencyKey?: string;
  threadId?: string;
}) => {
  const response = await fetchBackend('/admin/agent-runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<AgentRun>(response, '创建 Agent 运行失败');
};

export const createAdminDeepResearch = async (payload: {
  question: string;
  title?: string;
  successCriteria?: string[];
  idempotencyKey?: string;
  threadId?: string;
}) => {
  const response = await fetchBackend('/admin/deep-research', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<AgentRun>(response, '创建 DeepResearch 运行失败');
};

export const resumeAdminAgentRun = async (runId: string, payload: { waitId: string; resumeToken: string; payload: unknown }) => {
  const response = await fetchBackend(`/admin/agent-runs/${encodeURIComponent(runId)}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return unwrapApiResponse<AgentRun>(response, '恢复 Agent 运行失败');
};

export const cancelAdminAgentRun = async (runId: string, reason: string) => {
  const response = await fetchBackend(`/admin/agent-runs/${encodeURIComponent(runId)}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
  return unwrapApiResponse<AgentRun>(response, '取消 Agent 运行失败');
};

export const fetchAdminAgentArtifacts = async (params: { runId?: string; artifactType?: string; limit?: number } = {}) => {
  const response = await fetchBackend(withQuery('/admin/agent-artifacts', params));
  return unwrapApiResponse<AgentArtifactList>(response, '加载 Agent Artifact 失败');
};

export const fetchAdminAgentArtifactsForSsr = async (token: string, origin?: string) => {
  const response = await fetchBackend('/admin/agent-artifacts', { headers: { Authorization: `Bearer ${token}` } }, origin);
  return unwrapApiResponse<AgentArtifactList>(response, '加载 Agent Artifact 失败');
};

export const agentRunEventsUrl = (runId: string) =>
  buildBackendUrl(`/admin/agent-runs/${encodeURIComponent(runId)}/events`);
