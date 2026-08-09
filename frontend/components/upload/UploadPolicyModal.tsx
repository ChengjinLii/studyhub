import Link from 'next/link';

interface UploadPolicyModalProps {
  onClose: () => void;
}

export default function UploadPolicyModal({ onClose }: UploadPolicyModalProps) {
  return (
    <div className="modal-mask" onClick={onClose}>
      <div
        className="modal-card policy-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-policy-title"
        onClick={(event) => event.stopPropagation()}
      >
        <button className="modal-close" type="button" aria-label="关闭" onClick={onClose}>
          ×
        </button>
        <h2 id="upload-policy-title">投稿协议与隐私说明</h2>

        <h3>投稿与内容责任</h3>
        <ul>
          <li>请确认资料来源合法，并且你拥有上传、分享或授权平台展示该内容的权利。</li>
          <li>请勿上传违法、侵权、虚假、恶意或包含他人敏感个人信息的内容。</li>
          <li>平台可以根据审核、举报和版权申诉结果限制展示或下架相关内容。</li>
        </ul>

        <h3>收款码与收益结算</h3>
        <p className="help-text">
          投稿无需提交真实姓名、身份证号或同名支付宝账号。如需接收付费资料收益，只需在个人主页自愿上传可正常使用的收款码。
          收款码仅用于结算和对账，不会向普通用户或资料购买者公开。
        </p>

        <h3>个人信息处理</h3>
        <p className="help-text">
          平台会处理完成投稿、审核、文件存储、交易、安全审计和收益结算所必需的账号与业务信息，并按照目的明确、最小必要的原则控制使用范围。
        </p>

        <div className="policy-modal__actions">
          <Link href="/identity-info" target="_blank" rel="noreferrer">
            查看完整用户协议与隐私政策
          </Link>
          <button className="button primary small" type="button" onClick={onClose}>
            我已了解
          </button>
        </div>
      </div>
    </div>
  );
}
