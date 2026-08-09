import Link from 'next/link';

interface MePayoutSectionProps {
  totalEarnings: number;
}

export default function MePayoutSection({ totalEarnings }: MePayoutSectionProps) {
  return (
    <section className="card" id="payout">
      <div className="card-title">创作者收益</div>
      <div className="payout-qr-summary">
        <div className="payout-qr-summary__copy">
          <strong>累计收益 ¥{totalEarnings.toFixed(2)}</strong>
          <p className="help-text">
            平台按结算周期统计付费资料收益，由管理员核对后通过你在个人主页上传的收款码结算。
            当前无需提交真实姓名、身份证号或支付宝账号。
          </p>
        </div>
        <Link className="button ghost small" href="#payout-qr">
          查看 / 更新收款码
        </Link>
      </div>
    </section>
  );
}
