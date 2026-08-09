import { GetServerSideProps } from 'next';
import Link from 'next/link';
import NavBar from '../components/NavBar';
import { readSession } from '../lib/auth';
import { SessionUser } from '../types/user';

interface IdentityInfoPageProps {
  user: SessionUser | null;
}

export default function IdentityInfoPage({ user }: IdentityInfoPageProps) {
  return (
    <>
      <NavBar user={user} />
      <main className="container legal-page">
        <section className="card legal-page__intro">
          <p className="legal-page__eyebrow">STUDYHUB SERVICE TERMS</p>
          <h1>用户协议与隐私政策</h1>
          <p className="help-text">
            本说明适用于 StudyHub 的账号、资料投稿与获取、支付、社区、校园集市和创作者收益结算等功能。
            生效日期：2026 年 8 月 9 日。
          </p>
        </section>

        <section className="card">
          <h2>一、平台使用与内容责任</h2>
          <ul>
            <li>用户应依法使用账号和平台功能，不得冒用他人身份、破坏服务或规避平台权限与交易规则。</li>
            <li>投稿者应确认对上传资料拥有合法来源、使用权或传播权，不得上传违法、侵权、虚假或危害网络安全的内容。</li>
            <li>平台可以对投稿、评论、交易信息和举报进行审核，并在必要时采取限制展示、下架、冻结相关功能或配合争议处理等措施。</li>
            <li>付费资料的价格、交付方式和可见范围以资料详情页及支付页面展示为准；受控文件仍需在 StudyHub 完成登录、支付和权限校验后获取。</li>
          </ul>
        </section>

        <section className="card">
          <h2>二、收款码与创作者收益</h2>
          <p className="help-text">
            <strong>资料投稿本身不要求提交真实姓名、身份证号或同名支付宝账号。</strong>
            如需接收付费资料收益，用户只需在个人主页自愿上传本人可正常收款的二维码。
          </p>
          <ul>
            <li>收款码仅用于创作者收益结算、必要的对账和异常款项处理，不会在公开个人主页或资料详情页展示。</li>
            <li>收款码仅向用户本人和负责结算的授权管理员提供，普通用户和资料购买者无法查看。</li>
            <li>用户应确保收款码真实、有效且由本人合法使用；可随时在个人主页更新或删除。</li>
            <li>历史结算申请与交易记录可能因对账、争议处理、审计和系统兼容需要继续保留，但不会因此要求新投稿者补充身份信息。</li>
          </ul>
          <div className="inline-group legal-page__actions">
            <Link className="button primary small" href="/me#payout-qr">
              前往收款码设置
            </Link>
          </div>
        </section>

        <section className="card">
          <h2>三、我们处理哪些信息</h2>
          <ul>
            <li>账号信息：用户名、已绑定邮箱和登录验证信息。</li>
            <li>用户主动填写的信息：学校、学院、专业、年级、个人简介，以及自愿上传的收款码。</li>
            <li>业务记录：投稿、下载、购买、收藏、评论、举报、求购、校园集市和收益结算记录。</li>
            <li>安全与运行记录：设备、网络、访问和错误日志，用于身份验证、异常检测、限流、故障排查和安全审计。</li>
            <li>支付信息：订单号、支付渠道、金额和支付状态。平台不要求用户向 StudyHub 提供支付密码。</li>
          </ul>
          <p className="help-text">
            上述信息用于提供和维护服务、履行交易与结算、保护账号与平台安全、处理申诉举报以及改进产品。平台按照目的明确、最小必要的原则处理个人信息。
          </p>
        </section>

        <section className="card">
          <h2>四、信息共享、保存与安全</h2>
          <ul>
            <li>为完成文件存储、邮件验证、支付或收益结算，平台可能向对应的云存储、邮件和支付服务提供完成该功能所必需的信息。</li>
            <li>除法律法规要求、用户明确授权或履行服务所必需的情况外，平台不会向无关第三方公开用户个人信息。</li>
            <li>平台通过访问控制、传输保护、敏感信息脱敏、日志审计和备份等措施降低信息被未经授权访问、泄露或篡改的风险。</li>
            <li>信息保存期限以实现相应业务目的所需的合理期限为限；法律法规或交易争议处理另有要求的，按相应期限处理。</li>
          </ul>
        </section>

        <section className="card">
          <h2>五、用户权利与联系渠道</h2>
          <p className="help-text">
            用户可以在“我的”页面查看和修改个人资料、更新或删除收款码，并管理本人发布的内容。如需注销账号、处理历史信息、申诉或反馈隐私问题，
            可通过 <a href="mailto:chengjinli@std.uestc.edu.cn">chengjinli@std.uestc.edu.cn</a> 联系平台。
          </p>
          <h3>参考依据</h3>
          <ul>
            <li>
              <a href="https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm" target="_blank" rel="noreferrer">
                中华人民共和国个人信息保护法（国家互联网信息办公室）
              </a>
            </li>
            <li>
              <a href="https://www.npc.gov.cn/c2/c30834/202011/t20201119_308796.html" target="_blank" rel="noreferrer">
                中华人民共和国著作权法（中国人大网）
              </a>
            </li>
          </ul>
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<IdentityInfoPageProps> = async ({ req }) => {
  const session = readSession(req);
  return { props: { user: session.user } };
};
