import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const readSource = (relativePath: string) => readFileSync(join(process.cwd(), relativePath), 'utf8');

describe('public privacy and payout policy', () => {
  it('uses the payout QR policy instead of the legacy identity form', () => {
    const policy = readSource('pages/identity-info.tsx');
    const uploadPolicy = readSource('components/upload/UploadPolicyModal.tsx');
    const payoutSection = readSource('components/me/MePayoutSection.tsx');

    expect(policy).toContain('用户协议与隐私政策');
    expect(policy).toContain('资料投稿本身不要求提交真实姓名、身份证号或同名支付宝账号');
    expect(policy).toContain('/me#payout-qr');
    expect(uploadPolicy).toContain('投稿无需提交真实姓名、身份证号或同名支付宝账号');
    expect(payoutSection).toContain('查看 / 更新收款码');
    expect(payoutSection).not.toContain('idCardNo');
    expect(payoutSection).not.toContain('alipayAccount');
  });

  it('exposes one consolidated footer policy entry', () => {
    const app = readSource('pages/_app.tsx');
    const policyHrefMatches = app.match(/href="\/identity-info"/g) ?? [];

    expect(policyHrefMatches).toHaveLength(1);
    expect(app).not.toContain('身份信息说明');
  });
});
