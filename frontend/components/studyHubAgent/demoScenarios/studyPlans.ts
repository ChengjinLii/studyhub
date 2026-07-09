import { StudyHubAgentMessage } from '../types';
import { StudyHubAgentDemoScenario, StudyHubAgentDemoTurn } from './types';

const CPS_RECOMMENDATIONS = [
  {
    materialId: 209,
    title: 'CPS六年期末考答案自制（2019-2024）',
    tags: ['期末真题', '答案解析', '2019-2024'],
    reason: '先用六年真题判断题型分布和出题风格。',
    summary: '适合作为两周复习的主线材料。',
  },
  {
    materialId: 18,
    title: 'CPS-通信原理-Part3&4-助教讲义',
    tags: ['助教讲义', '期末速成'],
    reason: '用来补调制、解调、框图和公式推导。',
    summary: '适合在刷题前建立知识框架。',
  },
  {
    materialId: 168,
    title: '通信原理手写笔记',
    tags: ['日常学习笔记', '2023-2024'],
    reason: '适合碎片时间回看公式、概念和易错点。',
    summary: '可作为最后一周的查漏补缺材料。',
  },
];

const ESD_RECOMMENDATIONS = [
  {
    materialId: 137,
    title: 'ESD-电子系统设计-期末复习手写笔记',
    tags: ['期末速成', '手写笔记'],
    reason: '先建立 ESD 课程框架，整理常见模块和公式。',
    summary: '适合作为基础一般同学的第一轮复习入口。',
  },
  {
    materialId: 103,
    title: 'ESD样卷答案',
    tags: ['期末真题', '样卷答案'],
    reason: '用样卷识别题型、作答格式和易丢分位置。',
    summary: '适合第二阶段做限时训练。',
  },
  {
    materialId: 115,
    title: 'ESD-电子系统设计-2021年真题及答案',
    tags: ['2021', '真题答案'],
    reason: '用真题答案核对解题过程，形成错题清单。',
    summary: '适合冲刺阶段按题型复盘。',
  },
];

const CPS_OVERVIEW_FOLLOWUPS = [
  '帮我整理成两周复习计划',
  '通信原理有哪些常考题型和知识点？',
  '把推荐资料排成每日学习顺序',
];

const CPS_PLAN_FOLLOWUPS = [
  '把第 1-7 天细化到每天两小时',
  '把第 8-14 天改成冲刺刷题版',
  '按题型整理真题刷题清单',
];

const CPS_TOPICS_FOLLOWUPS = [
  '把高频题型排成刷题顺序',
  '给我一份公式速查清单',
  '给我一份考前 48 小时冲刺清单',
];

const CPS_DAILY_FOLLOWUPS = [
  '继续细化第 8-14 天冲刺安排',
  '给我一份每天 20 分钟错题复盘模板',
  '按题型整理真题刷题清单',
];

const CPS_SPRINT_FOLLOWUPS = [
  '给我一份考前 48 小时冲刺清单',
  '把高频题型排成刷题顺序',
  '给我一份公式速查清单',
];

const ESD_OVERVIEW_FOLLOWUPS = [
  'ESD 有哪些常考题型和知识点？',
  '给我总结一下两周复习计划',
  '按每天两小时安排复习节奏',
];

const ESD_PLAN_FOLLOWUPS = [
  '把 ESD 第 1-7 天细化到每天两小时',
  '按题型整理 ESD 刷题清单',
  '列一份 ESD 错题复盘清单',
];

const ESD_TOPICS_FOLLOWUPS = [
  '把这些题型排成刷题顺序',
  '给我总结一下两周复习计划',
  '列一份 ESD 错题复盘清单',
];

const ESD_DAILY_FOLLOWUPS = [
  '按题型整理 ESD 刷题清单',
  '给我一份 ESD 考前 48 小时冲刺清单',
  '列一份 ESD 错题复盘清单',
];

const CPS_DIRECT_QUERIES = [
  '两周后考通信原理基础一般怎么复习',
  '两周后考CPS基础一般怎么复习',
  '通信原理两周复习计划',
  'CPS两周复习计划',
  '通信原理有哪些常考题型和知识点',
  'CPS有哪些常考题型和知识点',
  '通信原理常考题型和知识点',
  'CPS常考题型和知识点',
];

const CPS_CONTEXT_FOLLOWUPS = [
  ...CPS_OVERVIEW_FOLLOWUPS,
  ...CPS_PLAN_FOLLOWUPS,
  ...CPS_TOPICS_FOLLOWUPS,
  ...CPS_DAILY_FOLLOWUPS,
  ...CPS_SPRINT_FOLLOWUPS,
  '按基础薄弱和冲刺刷题分阶段安排',
];

const ESD_DIRECT_QUERIES = [
  '两周后考ESD基础一般怎么复习',
  '两周后考电子系统设计基础一般怎么复习',
  'ESD 有哪些常考题型和知识点',
  '电子系统设计有哪些常考题型和知识点',
  'ESD 两周复习计划',
  '电子系统设计两周复习计划',
];

const ESD_CONTEXT_FOLLOWUPS = [
  ...ESD_OVERVIEW_FOLLOWUPS,
  ...ESD_PLAN_FOLLOWUPS,
  ...ESD_TOPICS_FOLLOWUPS,
  ...ESD_DAILY_FOLLOWUPS,
];

export const STUDY_PLAN_DEMO_SCENARIOS: StudyHubAgentDemoScenario[] = [
  {
    id: 'cps-two-week-review',
    courseNames: ['通信原理'],
    aliases: ['通信原理', 'CPS'],
    recommendations: CPS_RECOMMENDATIONS,
    resolve: (query) => {
      const intent = inferDemoIntent(query);
      if (intent === 'daily-hours') {
        return {
          answer: CPS_DAILY_HOURS_ANSWER,
          followups: CPS_DAILY_FOLLOWUPS,
          recommendations: CPS_RECOMMENDATIONS,
          stage: '细化安排中',
        };
      }
      if (intent === 'sprint') {
        return {
          answer: CPS_SPRINT_ANSWER,
          followups: CPS_SPRINT_FOLLOWUPS,
          recommendations: CPS_RECOMMENDATIONS,
          stage: '整理冲刺清单中',
        };
      }
      if (intent === 'plan' || intent === 'order' || intent === 'phases') {
        return {
          answer: CPS_PLAN_ANSWER,
          followups: CPS_PLAN_FOLLOWUPS,
          recommendations: CPS_RECOMMENDATIONS,
          stage: '整理两周计划中',
        };
      }
      if (intent === 'topics') {
        return {
          answer: CPS_TOPICS_ANSWER,
          followups: CPS_TOPICS_FOLLOWUPS,
          recommendations: CPS_RECOMMENDATIONS,
          stage: '整理题型重点中',
        };
      }
      return {
        answer: CPS_OVERVIEW_ANSWER,
        followups: CPS_OVERVIEW_FOLLOWUPS,
        recommendations: CPS_RECOMMENDATIONS,
        stage: '整理答案中',
      };
    },
  },
  {
    id: 'esd-two-week-review',
    courseNames: ['电子系统设计'],
    aliases: ['ESD', 'esd', '电子系统设计'],
    recommendations: ESD_RECOMMENDATIONS,
    resolve: (query) => {
      const intent = inferDemoIntent(query);
      if (intent === 'topics') {
        return {
          answer: ESD_TOPICS_ANSWER,
          followups: ESD_TOPICS_FOLLOWUPS,
          recommendations: ESD_RECOMMENDATIONS,
          stage: '整理题型重点中',
        };
      }
      if (intent === 'daily-hours') {
        return {
          answer: ESD_DAILY_HOURS_ANSWER,
          followups: ESD_DAILY_FOLLOWUPS,
          recommendations: ESD_RECOMMENDATIONS,
          stage: '细化安排中',
        };
      }
      if (intent === 'plan' || intent === 'order' || intent === 'phases' || intent === 'sprint') {
        return {
          answer: ESD_PLAN_ANSWER,
          followups: ESD_PLAN_FOLLOWUPS,
          recommendations: ESD_RECOMMENDATIONS,
          stage: '整理两周计划中',
        };
      }
      return {
        answer: ESD_OVERVIEW_ANSWER,
        followups: ESD_OVERVIEW_FOLLOWUPS,
        recommendations: ESD_RECOMMENDATIONS,
        stage: '整理答案中',
      };
    },
  },
];

export function inferScenarioFromContext(
  scenarios: StudyHubAgentDemoScenario[],
  query: string,
  messages: StudyHubAgentMessage[]
) {
  const queryText = normalizeDemoText(query);
  const contextText = normalizeDemoText(
    messages
      .slice(-8)
      .flatMap((message) => [
        message.content,
        ...(message.recommendations || []).flatMap((item) => [
          item.title || '',
          item.summary || '',
          item.reason || '',
          ...(item.tags || []),
        ]),
      ])
      .join(' ')
  );

  const directScenario = scenarios.find((scenario) =>
    scenario.aliases.some((alias) => queryText.includes(normalizeDemoText(alias)))
  );
  if (directScenario && isAllowedDirectDemoQuery(directScenario.id, queryText)) {
    return directScenario;
  }

  const contextScenario = scenarios.find((scenario) =>
    scenario.aliases.some((alias) => contextText.includes(normalizeDemoText(alias)))
  );
  if (contextScenario && isAllowedDemoFollowup(contextScenario.id, queryText)) {
    return contextScenario;
  }

  return undefined;
}

export function inferDemoIntent(query: string) {
  const text = normalizeDemoText(query);
  if (text.includes('第814天') || text.includes('第8到14天') || text.includes('冲刺刷题版') || text.includes('48小时')) {
    return 'sprint';
  }
  if (text.includes('每天两小时') || text.includes('每天2小时') || text.includes('两小时')) return 'daily-hours';
  if (text.includes('题型') || text.includes('知识点') || text.includes('考点') || text.includes('分数占比')) return 'topics';
  if (text.includes('顺序') || text.includes('每日学习')) return 'order';
  if (text.includes('分阶段') || text.includes('冲刺刷题') || text.includes('基础薄弱')) return 'phases';
  if (
    text.includes('复习计划') ||
    text.includes('两周计划') ||
    text.includes('两周复习') ||
    text.includes('整理成两周') ||
    text.includes('总结一下两周') ||
    text.includes('第1天') ||
    text.includes('第一天') ||
    text.includes('14天')
  ) {
    return 'plan';
  }
  return 'overview';
}

export function normalizeDemoText(value: string) {
  return value.replace(/[^\u4e00-\u9fa5A-Za-z0-9]+/g, '').toLowerCase();
}

function isAllowedDirectDemoQuery(scenarioId: string, queryText: string) {
  if (scenarioId === 'cps-two-week-review') {
    return matchesDemoPhrase(queryText, CPS_DIRECT_QUERIES);
  }
  if (scenarioId === 'esd-two-week-review') {
    return matchesDemoPhrase(queryText, ESD_DIRECT_QUERIES);
  }
  return false;
}

function isAllowedDemoFollowup(scenarioId: string, queryText: string) {
  if (scenarioId === 'cps-two-week-review') {
    return matchesDemoPhrase(queryText, CPS_CONTEXT_FOLLOWUPS);
  }
  if (scenarioId === 'esd-two-week-review') {
    return matchesDemoPhrase(queryText, ESD_CONTEXT_FOLLOWUPS);
  }
  return false;
}

function matchesDemoPhrase(queryText: string, phrases: string[]) {
  return phrases.some((phrase) => {
    const normalized = normalizeDemoText(phrase);
    return normalized.length >= 6 && queryText.includes(normalized);
  });
}

const CPS_OVERVIEW_ANSWER = `## 通信原理：两周复习路线

**结论：** 基础一般时，不建议一上来通读教材。先用助教讲义搭框架，再用真题答案校准题型，最后用手写笔记补公式和易错点。

### 推荐资料顺序

1. **《CPS-通信原理-Part3&4-助教讲义》**
   先看调制、解调、框图和公式推导，把知识点连起来。

2. **《CPS六年期末考答案自制（2019-2024）》**
   每两天刷一组真题，记录反复出现的题型。

3. **《通信原理手写笔记》**
   晚上快速回看公式、概念和错题对应知识点。

### 两周节奏

- **第 1-4 天：补框架。** 把 AM/FM/PM、ASK/PSK/QAM、信道与噪声这些核心模块先过一遍。
- **第 5-10 天：按题型刷真题。** 每次只解决一类题，避免今天刷计算题、明天又忘框图题。
- **第 11-13 天：错题回炉。** 把不会的题反查到讲义和笔记里，形成一页错题清单。
- **第 14 天：轻量复盘。** 只看公式、易错点和高频题型，不再开新坑。`;

const CPS_PLAN_ANSWER = `## 通信原理两周复习计划

目标是 **14 天内从“基础一般”推进到“能按题型稳定拿分”**。每天建议 2-3 小时；如果时间更少，优先完成“当天必须产出”。

### 第 1-4 天：先补框架

- **第 1 天：** 梳理课程目录和考试范围，标出完全不会的模块。产出一张知识框架图。
- **第 2 天：** 复习 AM、FM、PM 的概念、频谱和框图。产出 3 个核心公式和 2 道例题。
- **第 3 天：** 复习 ASK、PSK、QAM 的判决与性能。产出调制方式对比表。
- **第 4 天：** 复习信道、噪声、带宽、信噪比相关计算。产出计算题模板。

### 第 5-10 天：按题型刷题

- **第 5 天：** 刷第一套真题，不限时，重点看题型。产出题型清单。
- **第 6 天：** 对第 5 天错题逐题回查知识点。产出错题原因表。
- **第 7 天：** 刷第二套真题，开始限时训练。记录超时题。
- **第 8 天：** 汇总近两套真题的高频题型。产出高频题型排序。
- **第 9 天：** 专攻计算题，固定公式、单位和代入步骤。产出计算题步骤模板。
- **第 10 天：** 专攻框图和概念题，复述信号流程和模块作用。产出框图默写清单。

### 第 11-14 天：冲刺复盘

- **第 11 天：** 刷第三套真题，严格按考试节奏做。产出一套完整答卷。
- **第 12 天：** 只复盘错题，按“概念错 / 公式错 / 步骤错”分类。产出最终错题清单。
- **第 13 天：** 快速过所有高频公式和题型模板。产出一页速查表。
- **第 14 天：** 轻量复盘，保持手感，不再学新内容。产出考前检查清单。

### 执行优先级

1. **先真题后教材。** 教材只用来补不会的点，不做从头阅读。
2. **先题型后年份。** 同一类题连续刷 2-3 道，比机械刷完一年更有效。
3. **每天留 20 分钟复盘。** 不复盘的刷题基本等于“看过”。`;

const CPS_DAILY_HOURS_ANSWER = `## 第 1-7 天每天两小时安排

这 7 天的目标不是刷很多题，而是把框架搭起来，并完成第一轮真题诊断。

### 每天固定节奏

- **前 20 分钟：** 回顾昨天错题和公式。
- **中间 75 分钟：** 完成当天主任务。
- **最后 25 分钟：** 写下今天最容易丢分的 3 个点。

### 具体安排

- **第 1 天：** 整理课程目录、考试范围和完全不会的模块。产出一张知识框架图。
- **第 2 天：** 复习 AM、FM、PM 的概念、频谱和框图。产出 3 个核心公式。
- **第 3 天：** 复习 ASK、PSK、QAM 的判决和性能。产出调制方式对比表。
- **第 4 天：** 复习信道、噪声、带宽、信噪比相关计算。产出计算题模板。
- **第 5 天：** 刷一套真题，不限时，重点看题型和答案解析。
- **第 6 天：** 复盘第 5 天错题，按“概念 / 公式 / 计算 / 读题”分类。
- **第 7 天：** 只补最薄弱的 2 个模块，不新增资料。`;

const CPS_SPRINT_ANSWER = `## 第 8-14 天冲刺刷题版

后 7 天建议从“补知识”切换到“稳定拿分”。核心是限时、复盘和模板化。

### 第 8-10 天：按题型刷

- **第 8 天：** 刷第二套真题，开始计时，记录超时题。
- **第 9 天：** 专攻计算题，把公式、单位、代入步骤固定下来。
- **第 10 天：** 专攻框图和概念题，练习用标准语言解释模块作用。

### 第 11-13 天：整套模拟

- **第 11 天：** 严格限时做一套题，训练卷面节奏。
- **第 12 天：** 复盘错题，只处理反复错的题型。
- **第 13 天：** 压缩成一页公式表和一页错题清单。

### 第 14 天：轻量保持手感

- 上午过公式表。
- 下午做 2-3 道典型题。
- 晚上停止高强度刷题，只看错题原因。`;

const CPS_TOPICS_ANSWER = `## 通信原理常见题型与复习抓手

### 高频题型

- **概念判断：** 常考调制方式、带宽、信噪比和系统组成。复习时建一张概念对比表。
- **公式计算：** 常见带宽、功率、信噪比和误码率相关计算。固定“写公式 -> 代入 -> 单位检查”三步。
- **框图分析：** 常考调制 / 解调系统框图和模块作用。每天默写 1 个典型框图。
- **综合题：** 多个模块串联，要求解释过程。用真题答案学习标准表达。

建议把真题按题型拆开练：先把同类题做熟，再回到整套卷训练速度。`;

const ESD_OVERVIEW_ANSWER = `## ESD：两周复习路线

**结论：** ESD 更适合按“模块理解 + 样卷题型 + 真题复盘”推进。基础一般时，先把常见模块和题型看清楚，再进入限时训练。

### 推荐资料顺序

1. **《ESD-电子系统设计-期末复习手写笔记》**
   先搭课程框架，整理概念、模块和公式。

2. **《ESD样卷答案》**
   用样卷看题型、作答格式和常见扣分点。

3. **《ESD-电子系统设计-2021年真题及答案》**
   用真题答案复盘解题路径，形成错题清单。

### 两周打法

- **第 1-4 天：框架优先。** 先把电子系统设计中的模块、设计流程、关键指标和常见公式整理出来。
- **第 5-9 天：样卷和真题识别题型。** 每天聚焦一种题型，记录标准作答步骤。
- **第 10-13 天：限时训练和错题回查。** 按考试节奏做题，错题回到笔记里定位知识点。
- **第 14 天：轻量复盘。** 只看错题、公式、题型模板和容易混淆的概念。`;

const ESD_TOPICS_ANSWER = `## ESD 常考题型和知识点

可以把 ESD 复习拆成 5 类题型，每一类都对应一套固定训练方式。

### 高频题型

- **系统设计流程：** 给出需求，要求分析指标、模块划分或设计思路。练习“需求 -> 指标 -> 模块 -> 验证”的表达模板。
- **模拟 / 数字接口：** 分析信号连接、采样、转换和接口约束。建接口条件表，写清输入、输出和限制。
- **电路与模块计算：** 根据参数完成基础计算或判断设计是否满足指标。每道题保留公式、单位和结论三行。
- **时序 / 控制逻辑：** 判断流程、状态变化或控制顺序。用流程图或状态表复述题目。
- **综合设计题：** 多模块组合，要求解释方案优缺点。先列模块，再写权衡，不要直接堆公式。

### 推荐复习顺序

1. 先用手写笔记把模块和公式过一遍。
2. 再用样卷答案学习“标准答案长什么样”。
3. 最后用真题答案做限时训练，错题回查笔记。`;

const ESD_PLAN_ANSWER = `## ESD 两周复习计划

目标是 **14 天内完成框架整理、题型训练和考前复盘**。默认每天 2 小时；如果当天只有 1 小时，优先完成“必须产出”。

### 第 1-4 天：框架整理

- **第 1 天：** 明确考试范围，通读手写笔记目录。产出一张课程模块清单。
- **第 2 天：** 梳理系统设计流程：需求、指标、模块、验证。产出设计流程模板。
- **第 3 天：** 复习常见接口、信号连接和约束条件。产出接口条件表。
- **第 4 天：** 复习基础计算和公式，统一单位。产出公式速查表。

### 第 5-10 天：题型训练

- **第 5 天：** 看样卷答案，识别题型和答题格式。产出题型分类表。
- **第 6 天：** 专练流程 / 设计思路题。产出 2 道题的标准表达。
- **第 7 天：** 专练计算 / 判断题。产出计算步骤模板。
- **第 8 天：** 做一套真题，不限时，先保证会分析。产出第一版错题清单。
- **第 9 天：** 对照答案复盘第 8 天错题。产出错因分类。
- **第 10 天：** 再做一轮题型训练，重点补弱项。产出弱项题型清单。

### 第 11-14 天：限时冲刺

- **第 11 天：** 限时做一套题，训练速度和卷面组织。产出一套完整答题记录。
- **第 12 天：** 只看错题和高频模块，回查手写笔记。产出最终错题表。
- **第 13 天：** 背诵公式、流程模板和接口约束。产出一页考前速查。
- **第 14 天：** 轻量复盘，不再开新资料。产出考前 30 分钟清单。

### 每天 2 小时分配

- **前 30 分钟：** 回顾昨天错题和公式。
- **中间 70 分钟：** 做当天主任务。
- **最后 20 分钟：** 写下“今天最容易丢分的 3 个点”。`;

const ESD_DAILY_HOURS_ANSWER = `## ESD 每天两小时安排

每天两小时足够完成一轮有效复习，但要避免“只看不写”。每一天都要有可检查产出。

### 第 1-4 天：框架和公式

- **第 1 天：** 通读手写笔记目录，整理课程模块清单。
- **第 2 天：** 梳理系统设计流程，写出“需求 -> 指标 -> 模块 -> 验证”模板。
- **第 3 天：** 整理接口、信号连接和约束条件。
- **第 4 天：** 整理公式和单位，做 3 道基础计算题。

### 第 5-7 天：样卷诊断

- **第 5 天：** 看样卷答案，识别题型和标准表达。
- **第 6 天：** 专练流程 / 设计思路题，写 2 道完整答案。
- **第 7 天：** 专练计算 / 判断题，形成错题清单。

### 每天收尾

- 写下当天 3 个薄弱点。
- 标出明天必须回查的 1 个知识点。
- 不在最后 20 分钟打开新资料。`;
