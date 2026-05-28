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
        aria-label="平台隐私政策与用户协议"
        onClick={(event) => event.stopPropagation()}
      >
        <button className="modal-close" type="button" aria-label="关闭" onClick={onClose}>
          ×
        </button>
        <h2>平台隐私政策/用户协议</h2>
        <h3>为什么需要身份信息？</h3>
        <p className="help-text">
          我们仅在<strong>提现</strong>等涉及向个人支付创作者收益的环节，要求填写姓名、身份证号及同名支付宝账号，主要基于两类需求：
        </p>
        <ol>
          <li>
            <strong>税务合规（依法扣缴申报）</strong>
            <p className="help-text">
              当平台向个人支付所得时，通常需要依法履行个人所得税的扣缴申报义务。个人所得税法明确：扣缴义务人应当按照国家规定办理
              <strong>全员全额扣缴申报</strong>。（
              <a href="https://gongbao.court.gov.cn/Details/8387ed08755a9be653320a8fc12c8e.html" target="_blank" rel="noreferrer">[1]</a>
              ）在扣缴申报制度下，扣缴义务人需要向税务机关报送包括<strong>姓名、证件信息等</strong>在内的个人基础信息、支付所得项目与数额等涉税信息。（
              <a href="https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193745/content.html" target="_blank" rel="noreferrer">[2]</a>
              ）关于自然人纳税人识别号的规定/解读也强调：自然人首次办理涉税事项时，需要向税务机关或扣缴义务人提供有效身份证件及相关信息。（
              <a href="https://shanghai.chinatax.gov.cn/zcfw/zcjd/201812/t443337.html" target="_blank" rel="noreferrer">[3]</a>
              ）
            </p>
          </li>
          <li>
            <strong>打款成功与安全（同名校验与防冒领）</strong>
            <p className="help-text">
              同名支付宝信息用于减少转账失败、退回等情况，并降低冒领、盗刷、异常提现风险。
            </p>
          </li>
        </ol>
        <h3>身份信息如何使用与保护</h3>
        <h4>使用范围（用途限制）</h4>
        <ul>
          <li>税务扣缴申报与合规留存（按规定报送必要的个人基础信息与所得信息）。</li>
          <li>提现审核与打款校验（核验收款人实名信息与同名支付宝）。</li>
          <li>风控与纠纷处理（异常提现、申诉、争议仲裁时用于核验与审计）。</li>
        </ul>
        <h4>保护措施（合规要求）</h4>
        <p className="help-text">
          我们遵循《个人信息保护法》的基本要求：以<strong>明确目的、最小必要</strong>方式收集，公开透明说明用途，并采取必要安全措施。包括但不限于：加密存储、脱敏展示、权限控制、访问留痕与审计。（
          <a href="https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm" target="_blank" rel="noreferrer">[4]</a>
          ）
        </p>
        <h3>谁能看到我的信息？</h3>
        <ul>
          <li>✅ 可见范围：仅限与提现审核、税务申报/对账、风控合规相关的人员在履职范围内查看。</li>
          <li>❌ 不可见范围：其他普通用户、购买者、非相关岗位人员均不可见。</li>
          <li>
            ✅ 访问可追溯：对敏感信息的访问会记录日志，用于安全审计与责任追踪。（
            <a href="https://npcobserver.com/wp-content/uploads/2023/09/2021-Personal-Information-Protection-Law_Gazette.pdf" target="_blank" rel="noreferrer">[5]</a>
            ）
          </li>
        </ul>
        <h4>参考链接</h4>
        <ul>
          <li>
            <a href="https://gongbao.court.gov.cn/Details/8387ed08755a9be653320a8fc12c8e.html" target="_blank" rel="noreferrer">
              [1] 中华人民共和国个人所得税法（公报网）
            </a>
          </li>
          <li>
            <a href="https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193745/content.html" target="_blank" rel="noreferrer">
              [2] 国家税务总局关于印发《个人所得税全员全额扣缴申报管理》相关内容
            </a>
          </li>
          <li>
            <a href="https://shanghai.chinatax.gov.cn/zcfw/zcjd/201812/t443337.html" target="_blank" rel="noreferrer">
              [3] 自然人纳税人识别号有关事项解读（上海税务）
            </a>
          </li>
          <li>
            <a href="https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm" target="_blank" rel="noreferrer">
              [4] 中华人民共和国个人信息保护法（国家网信办）
            </a>
          </li>
          <li>
            <a href="https://npcobserver.com/wp-content/uploads/2023/09/2021-Personal-Information-Protection-Law_Gazette.pdf" target="_blank" rel="noreferrer">
              [5] 个人信息保护法全文（NPC Observer）
            </a>
          </li>
        </ul>
      </div>
    </div>
  );
}
