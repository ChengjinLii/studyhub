import { describe, expect, it } from 'vitest';
import {
  buildStudyHubAgentContext,
  normalizeFollowups,
} from '../../components/studyHubAgent/useStudyHubAgentChat';
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

  it('deduplicates follow-up prompts', () => {
    const followups = normalizeFollowups(
      [
        '帮我整理成两周复习计划',
        '把第 1-7 天细化到每天两小时',
        '把第 1-7 天细化到每天两小时',
      ],
      '帮我整理成两周复习计划'
    );

    expect(followups).toEqual(['把第 1-7 天细化到每天两小时']);
  });

  it('leaves follow-up semantics to the backend model reviewer', () => {
    const followups = normalizeFollowups([
      '需要我帮你分析2020-2022年真题中各类题型的分数占比吗',
      '是否想重点突破某一种题型（如计算题或设计题）的解题思路',
      '根据你的复习笔记，定制一个题型专项复习计划',
    ]);

    expect(followups).toEqual([
      '需要我帮你分析2020-2022年真题中各类题型的分数占比吗',
      '是否想重点突破某一种题型（如计算题或设计题）的解题思路',
      '根据你的复习笔记，定制一个题型专项复习计划',
    ]);
  });

});
