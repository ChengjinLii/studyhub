import { describe, expect, it } from 'vitest';
import { ensureApiSuccess, unwrapApiResponse } from '../../lib/apiEnvelope';

const jsonResponse = (payload: unknown, status = 200) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('apiEnvelope', () => {
  it('unwraps successful data envelopes', async () => {
    await expect(unwrapApiResponse<{ id: number }>(jsonResponse({ ok: true, data: { id: 7 } }), '失败')).resolves.toEqual({
      id: 7,
    });
  });

  it('allows success envelopes without data when requested', async () => {
    await expect(ensureApiSuccess(jsonResponse({ ok: true }), '失败')).resolves.toMatchObject({ ok: true });
  });

  it('throws ApiError with backend code and message', async () => {
    await expect(
      unwrapApiResponse(jsonResponse({ ok: false, msg: '无权限', error: { code: 'FORBIDDEN' } }, 403), '失败')
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 403,
      code: 'FORBIDDEN',
    });
  });
});
