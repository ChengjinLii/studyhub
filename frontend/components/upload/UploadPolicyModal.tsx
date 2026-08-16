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

        <h3>文件风险扫描与隔离</h3>
        <ul>
          <li>站内文件投稿后会先进入隔离状态，在自动风险扫描完成前暂不开放下载。</li>
          <li>平台会进行文件结构检查，并对可疑文件、Office 文档和压缩包等调用恶意软件扫描；检查所需的临时副本会在处理完成后删除。</li>
          <li>存在恶意特征、加密或无法可靠检查的文件可能被延迟发布、限制下载或拒绝展示；自动检查不能替代投稿者对文件合法性和安全性的责任。</li>
        </ul>

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
