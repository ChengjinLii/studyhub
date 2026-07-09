const DEMO_WAIT_STAGES = ['理解问题中', '检索资料中', '匹配资料中'] as const;
const DEMO_WAIT_DURATIONS_MS = [1050, 1350, 1250, 1100] as const;

export async function runStudyHubAgentDemoWait(
  onStage: (stage: string) => void,
  finalStage = '整理答案中'
) {
  const stages = [...DEMO_WAIT_STAGES, finalStage];
  for (let index = 0; index < stages.length; index += 1) {
    const stage = stages[index];
    onStage(stage);
    await wait(DEMO_WAIT_DURATIONS_MS[index] ?? 700);
  }
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
