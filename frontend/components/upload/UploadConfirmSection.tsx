import UploadSectionLabel from './UploadSectionLabel';

interface UploadConfirmSectionProps {
  isEditing: boolean;
  isExperience: boolean;
  isQuickMode: boolean;
  copyrightOwner: string;
  maxCopyrightLength: number;
  submitting: boolean;
  uploadProgress: number | null;
  status: { type: 'success' | 'error'; message: string } | null;
  onCopyrightOwnerChange: (value: string) => void;
  onPolicyOpen: () => void;
}

export default function UploadConfirmSection({
  isEditing,
  isExperience,
  isQuickMode,
  copyrightOwner,
  maxCopyrightLength,
  submitting,
  uploadProgress,
  status,
  onCopyrightOwnerChange,
  onPolicyOpen,
}: UploadConfirmSectionProps) {
  return (
    <div className="upload-section-shell" id="upload-confirm">
      <div className="upload-section-heading">
        <div className="upload-section-heading__copy">
          <h2 className="upload-section-heading__title">发布确认</h2>
        </div>
      </div>
      <section className="card upload-main-card upload-section-card">
        <div className="form-grid upload-section-grid">
          {!isExperience && !isQuickMode && (
            <div className="form-item full">
              <UploadSectionLabel htmlFor="copyrightOwner" text="版权持有者" optional />
              <input
                id="copyrightOwner"
                value={copyrightOwner}
                onChange={(e) => onCopyrightOwnerChange(e.target.value)}
                maxLength={maxCopyrightLength}
                placeholder="不超过 8 个字符，如：张三"
              />
              <p className="help-text">
                若为学校官网或个人原创资料可不填；如来源于其他同学/渠道，请先征得同意再发布，并填写对方姓名。
              </p>
            </div>
          )}
          <div className="form-item full">
            <label className="choice agreement">
              <input type="checkbox" required />
              <span>
                我已阅读并同意
                <button
                  type="button"
                  className="policy-link"
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    onPolicyOpen();
                  }}
                >
                  平台隐私政策/用户协议
                </button>
                ，确认资料合法且授权发布。平台运营初期由平台统一收费与分发，抽成比例暂定 10%，用于运营成本和维护；后续若有调整将提前公告，请知悉。
              </span>
            </label>
          </div>
          <div className="form-item">
            <button className="button primary" type="submit" disabled={submitting}>
              {submitting
                ? isEditing
                  ? '更新中...'
                  : '提交中...'
                : isEditing
                  ? isExperience
                    ? '更新经验分享'
                    : '更新资料'
                  : isExperience
                    ? '提交经验分享'
                    : isQuickMode
                      ? '一键投稿'
                      : '提交资料'}
            </button>
          </div>
          {isExperience && uploadProgress !== null && (
            <div className="form-item full">
              <div className="upload-progress" aria-live="polite">
                <progress value={uploadProgress} max={100} />
                <span className="upload-percent">{uploadProgress}%</span>
              </div>
            </div>
          )}
          {status && <p className={status.type === 'error' ? 'error-text' : 'success-text'}>{status.message}</p>}
        </div>
      </section>
    </div>
  );
}
