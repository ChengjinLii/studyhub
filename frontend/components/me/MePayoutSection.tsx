import { FormEvent } from 'react';
import Link from 'next/link';
import { PayoutApplication } from '../../types/payout';

interface PayoutFormState {
  alipayAccount: string;
  alipayName: string;
  realName: string;
  idCardNo: string;
  contactType: string;
  contactValue: string;
  notes: string;
}

type AlertMessage = { type: 'success' | 'error'; message: string } | null;

interface MePayoutSectionProps {
  payoutForm: PayoutFormState;
  payoutLoading: boolean;
  payoutMessage: AlertMessage;
  payoutApp: PayoutApplication | null;
  payoutStatusText: string | null;
  onPayoutFormChange: (patch: Partial<PayoutFormState>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

export default function MePayoutSection({
  payoutForm,
  payoutLoading,
  payoutMessage,
  payoutApp,
  payoutStatusText,
  onPayoutFormChange,
  onSubmit,
}: MePayoutSectionProps) {
  return (
    <section className="card" id="payout">
      <div className="card-title">创作者收益申请</div>
      <form className="form-grid" onSubmit={onSubmit}>
        <div className="form-item">
          <label htmlFor="payout-alipay-account">支付宝账号</label>
          <input
            id="payout-alipay-account"
            value={payoutForm.alipayAccount}
            onChange={(e) => onPayoutFormChange({ alipayAccount: e.target.value })}
            placeholder="用于收款的支付宝账号"
            required
          />
        </div>
        <div className="form-item">
          <label htmlFor="payout-real-name">
            收款人姓名（需与支付宝实名一致）
            <Link
              href="/identity-info"
              className="identity-help-link"
              title="为了向创作者支付收益并依法办理个人所得税扣缴申报，我们需要采集收款人姓名、身份证号等身份信息，并做同名支付宝校验。信息仅用于提现审核、税务申报与风控合规，严格加密与脱敏。"
              aria-label="为什么需要身份信息"
            >
              ？为什么需要我的身份信息
            </Link>
          </label>
          <input
            id="payout-real-name"
            value={payoutForm.realName}
            onChange={(e) => onPayoutFormChange({ realName: e.target.value, alipayName: e.target.value })}
            placeholder="将用于实名核验"
            required
          />
        </div>
        <div className="form-item">
          <label htmlFor="payout-id-card">身份证号</label>
          <input
            id="payout-id-card"
            value={payoutForm.idCardNo}
            onChange={(e) => onPayoutFormChange({ idCardNo: e.target.value })}
            placeholder="仅用于实名核验"
            required
          />
        </div>
        <div className="form-item full">
          <p className="help-text">实名信息仅用于核验与打款，同名校验不通过将无法结算。</p>
        </div>
        <div className="form-item">
          <label htmlFor="payout-contact-type">联系方式类型</label>
          <select
            id="payout-contact-type"
            value={payoutForm.contactType}
            onChange={(e) => onPayoutFormChange({ contactType: e.target.value })}
          >
            <option value="WECHAT">微信</option>
            <option value="QQ">QQ</option>
            <option value="PHONE">手机号</option>
            <option value="OTHER">其他</option>
          </select>
        </div>
        <div className="form-item">
          <label htmlFor="payout-contact-value">联系方式</label>
          <input
            id="payout-contact-value"
            value={payoutForm.contactValue}
            onChange={(e) => onPayoutFormChange({ contactValue: e.target.value })}
            placeholder="请输入联系账号，便于结算沟通"
            required
          />
        </div>
        <div className="form-item full">
          <p className="help-text">最低提现金额为 10 元。</p>
        </div>
        <div className="form-item full">
          <label htmlFor="payout-notes">备注（可选）</label>
          <textarea
            id="payout-notes"
            value={payoutForm.notes}
            onChange={(e) => onPayoutFormChange({ notes: e.target.value })}
            rows={3}
            placeholder="补充结算说明"
          />
        </div>
        <div className="form-item">
          <button className="button primary" type="submit" disabled={payoutLoading}>
            {payoutLoading ? '提交中...' : '提交收益申请'}
          </button>
        </div>
      </form>
      {payoutMessage && (
        <p className={payoutMessage.type === 'error' ? 'error-text' : 'success-text'}>{payoutMessage.message}</p>
      )}
      {payoutApp && (
        <div className="help-text" style={{ marginTop: 8 }}>
          <div>状态：{payoutApp.status || '未提交'}</div>
          <div>周期：{payoutApp.cycleKey || '-'}</div>
          <div>说明：{payoutStatusText}</div>
        </div>
      )}
    </section>
  );
}
