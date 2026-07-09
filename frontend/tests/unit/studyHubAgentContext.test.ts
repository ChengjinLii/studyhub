import { describe, expect, it } from 'vitest';
import {
  buildStudyHubAgentContext,
  normalizeFollowups,
} from '../../components/studyHubAgent/useStudyHubAgentChat';
import { resolveStudyHubAgentDemoTurn } from '../../components/studyHubAgent/demoScenarios';
import { StudyHubAgentMessage } from '../../components/studyHubAgent/types';

const message = (
  id: number,
  role: StudyHubAgentMessage['role'],
  content: string,
  recommendations: StudyHubAgentMessage['recommendations'] = [],
  imageAttachments: StudyHubAgentMessage['imageAttachments'] = []
): StudyHubAgentMessage => ({
  id: String(id),
  role,
  content,
  recommendations,
  imageAttachments,
});

describe('studyHubAgentContext', () => {
  it('keeps an early course and material summary for long follow-up conversations', () => {
    const messages: StudyHubAgentMessage[] = [
      message(1, 'user', '我想复习 ESD，也就是电子系统设计'),
      message(2, 'assistant', '可以先看这两份资料', [
        { materialId: 201, title: 'ESD-电子系统设计-2021年真题及答案' },
      ]),
      ...Array.from({ length: 18 }, (_, index) =>
        message(index + 3, index % 2 === 0 ? 'user' : 'assistant', `后续讨论 ${index}`)
      ),
    ];

    const context = buildStudyHubAgentContext(messages, '考题风格帮我分析一下');

    expect(context.length).toBeLessThanOrEqual(1000);
    expect(context).toContain('早期上下文摘要');
    expect(context).toContain('电子系统设计');
    expect(context).toContain('#201');
    expect(context).toContain('ESD-电子系统设计-2021年真题及答案');
    expect(context).not.toContain('考题风格帮我分析一下');
  });

  it('redacts private values before sending compact context', () => {
    const messages: StudyHubAgentMessage[] = [
      message(1, 'user', '我的 token: demo-secret-value，邮箱是 test@example.com'),
      message(2, 'assistant', '手机号 13800138000 不应该出现在上下文'),
    ];

    const context = buildStudyHubAgentContext(messages, '继续');

    expect(context).toContain('[redacted-secret]');
    expect(context).toContain('[redacted-email]');
    expect(context).toContain('[redacted-phone]');
    expect(context).not.toContain('demo-secret-value');
    expect(context).not.toContain('test@example.com');
    expect(context).not.toContain('13800138000');
  });

  it('keeps image attachment metadata out of compact context data urls', () => {
    const messages: StudyHubAgentMessage[] = [
      message(1, 'user', '帮我看这张题目截图', [], [
        {
          id: 'img-1',
          name: 'question.png',
          mimeType: 'image/png',
          dataUrl: 'data:image/png;base64,secret-image-data',
          sizeBytes: 128,
        },
      ]),
    ];

    const context = buildStudyHubAgentContext(messages, '这题怎么做');

    expect(context).toContain('question.png(image/png, 128B)');
    expect(context).not.toContain('secret-image-data');
    expect(context).not.toContain('data:image/png');
  });

  it('filters duplicate and fill-in follow-up prompts', () => {
    const followups = normalizeFollowups(
      [
        '帮我整理成两周复习计划',
        '你的考试日期和每天可复习时间是多少？',
        '把第 1-7 天细化到每天两小时',
        '把第 1-7 天细化到每天两小时',
      ],
      '帮我整理成两周复习计划'
    );

    expect(followups).toEqual(['把第 1-7 天细化到每天两小时']);
  });

  it('normalizes assistant-voice follow-up prompts into user requests', () => {
    const followups = normalizeFollowups([
      '需要我帮你分析2020-2022年真题中各类题型的分数占比吗',
      '是否想重点突破某一种题型（如计算题或设计题）的解题思路',
      '根据你的复习笔记，定制一个题型专项复习计划',
    ]);

    expect(followups).toEqual([
      '分析2020-2022年真题中各类题型的分数占比',
      '重点突破某一种题型（如计算题或设计题）的解题思路',
      '根据我的复习笔记，定制一个题型专项复习计划',
    ]);
  });

  it('filters generic preference and profile follow-up prompts', () => {
    const followups = normalizeFollowups([
      '我更想要真题、笔记还是经验分享',
      '限定学校、学院或专业',
      '结合我的专业和年级调整推荐顺序',
      '按题型整理真题刷题清单',
    ]);

    expect(followups).toEqual(['按题型整理真题刷题清单']);
  });

  it('uses the CPS demo overview for the first review question', () => {
    const turn = resolveStudyHubAgentDemoTurn('两周后考通信原理，基础一般，怎么复习？', []);

    expect(turn?.answer).toContain('通信原理：两周复习路线');
    expect(turn?.answer).toContain('推荐资料顺序');
    expect(turn?.answer).not.toContain('| 天数 |');
    expect(turn?.answer).not.toMatch(/\u6f14\u793a|\u6f14\u793a\u53e3\u5f84/);
    expect(turn?.stage).toBe('整理答案中');
    expect(turn?.followups).toContain('帮我整理成两周复习计划');
    expect(turn?.recommendations.map((item) => item.materialId)).toEqual([209, 18, 168]);
  });

  it('uses different CPS follow-ups across overview, plan, and topics turns', () => {
    const overview = resolveStudyHubAgentDemoTurn('两周后考通信原理，基础一般，怎么复习？', []);
    const plan = resolveStudyHubAgentDemoTurn('帮我整理成两周复习计划', [
      message(1, 'assistant', overview?.answer || '', overview?.recommendations || []),
    ]);
    const topics = resolveStudyHubAgentDemoTurn('通信原理有哪些常考题型和知识点？', []);

    expect(overview?.followups).not.toEqual(plan?.followups);
    expect(plan?.followups).not.toEqual(topics?.followups);
    expect(topics?.followups).toContain('给我一份公式速查清单');
  });

  it('uses prior CPS context for a generic plan follow-up', () => {
    const messages = [
      message(1, 'user', '两周后考通信原理，基础一般，怎么复习？'),
      message(2, 'assistant', '可以先按 CPS 真题和助教讲义来复习', [
        { materialId: 209, title: 'CPS六年期末考答案自制（2019-2024）' },
      ]),
    ];

    const turn = resolveStudyHubAgentDemoTurn('帮我整理成两周复习计划', messages);

    expect(turn?.answer).toContain('通信原理两周复习计划');
    expect(turn?.answer).toContain('第 1 天');
    expect(turn?.answer).not.toContain('| 天数 |');
    expect(turn?.followups).toContain('按题型整理真题刷题清单');
  });

  it('supports an ESD demo with topics and a context-aware plan follow-up', () => {
    const firstTurn = resolveStudyHubAgentDemoTurn('两周后考 esd，基础一般，怎么复习？', []);
    expect(firstTurn?.answer).toContain('ESD：两周复习路线');
    expect(firstTurn?.followups).toContain('ESD 有哪些常考题型和知识点？');

    const topicTurn = resolveStudyHubAgentDemoTurn('ESD 有哪些常考题型和知识点？', []);
    expect(topicTurn?.answer).toContain('ESD 常考题型和知识点');
    expect(topicTurn?.answer).toContain('综合设计题');

    const planTurn = resolveStudyHubAgentDemoTurn('给我总结一下两周复习计划', [
      message(1, 'user', '两周后考 esd，基础一般，怎么复习？'),
      message(2, 'assistant', firstTurn?.answer || '', firstTurn?.recommendations || []),
    ]);
    expect(planTurn?.answer).toContain('ESD 两周复习计划');
    expect(planTurn?.answer).toContain('第 14 天');
    expect(planTurn?.answer).not.toContain('| 天数 |');
  });

  it('keeps non-demo questions on the normal backend path', () => {
    const messages = [
      message(1, 'user', '两周后考通信原理，基础一般，怎么复习？'),
      message(2, 'assistant', '可以先按 CPS 真题和助教讲义来复习', [
        { materialId: 209, title: 'CPS六年期末考答案自制（2019-2024）' },
      ]),
    ];

    expect(resolveStudyHubAgentDemoTurn('通信原理教材有哪些版本？', [])).toBeNull();
    expect(resolveStudyHubAgentDemoTurn('傅里叶变换怎么理解？', messages)).toBeNull();
    expect(resolveStudyHubAgentDemoTurn('给我总结一下两周复习计划', [])).toBeNull();
  });
});
