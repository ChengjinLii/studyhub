import Link from 'next/link';

const UploadTitleIcon = () => (
  <span className="upload-title-icon" aria-hidden="true">
    <svg viewBox="0 0 24 24" role="img" focusable="false">
      <path d="M3.5 7.5L12 3l8.5 4.5L12 12z" />
      <path d="M3.5 12L12 16.5 20.5 12" />
      <path d="M3.5 16.5L12 21l8.5-4.5" />
    </svg>
  </span>
);

interface UploadHeroProps {
  isEditing: boolean;
  isRequestResponse: boolean;
  uploadMode: 'material' | 'experience';
  pageTitle: string;
  experienceHeading: string;
  resolvedExperienceExtraTag: string | null;
  quickPanelOpen: boolean;
  quickSelectedOption: string | null;
  quickUploadOptions: string[];
  onSwitchUploadMode: (mode: 'material' | 'experience') => void;
  onToggleQuickPanel: () => void;
  onQuickOptionSelect: (option: string) => void;
}

export default function UploadHero({
  isEditing,
  isRequestResponse,
  uploadMode,
  pageTitle,
  experienceHeading,
  resolvedExperienceExtraTag,
  quickPanelOpen,
  quickSelectedOption,
  quickUploadOptions,
  onSwitchUploadMode,
  onToggleQuickPanel,
  onQuickOptionSelect,
}: UploadHeroProps) {
  return (
    <section className="card me-hero upload-hero" id="upload-overview">
      <div className="me-hero__inner">
        <div className="me-hero__intro">
          <div className="me-hero__eyebrow">{isEditing ? '编辑模式' : '投稿工作台'}</div>
          <div className="me-hero__title-row">
            <h1 className="me-hero__title upload-title">
              <UploadTitleIcon />
              <span>{pageTitle}</span>
            </h1>
          </div>
          {uploadMode === 'experience' && (
            <p className="me-hero__subtitle upload-hero__subtitle">
              当前方向：{experienceHeading}
              {resolvedExperienceExtraTag ? ` · 自动附加 #${resolvedExperienceExtraTag}` : ''}
            </p>
          )}
          {!isEditing && !isRequestResponse && (
            <div className="upload-hero__actions">
              <div className="upload-hero__tools">
                {uploadMode === 'experience' ? (
                  <>
                    <Link className="upload-hero__action upload-hero__action--secondary" href="/column">
                      <span className="upload-hero__action-label">返回学汇专栏</span>
                    </Link>
                    <button
                      type="button"
                      className="upload-hero__action upload-hero__action--secondary active"
                      onClick={() => onSwitchUploadMode('material')}
                    >
                      <span className="upload-hero__action-label">返回资料投稿</span>
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className={`upload-hero__action${quickPanelOpen ? ' active' : ''}`}
                      onClick={onToggleQuickPanel}
                    >
                      <span className="upload-hero__action-label">
                        {quickPanelOpen ? '收起一键投稿' : '太麻烦？一键投稿'}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="upload-hero__action upload-hero__action--secondary"
                      onClick={() => onSwitchUploadMode('experience')}
                    >
                      <span className="upload-hero__action-label">开始经验分享</span>
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
        {!isEditing && !isRequestResponse && quickUploadOptions.length > 0 && (
          <div className="upload-hero__pills">
            <div className="upload-option-pills">
              {quickUploadOptions.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`button ${quickSelectedOption === option ? 'primary' : 'ghost'} small`}
                  onClick={() => onQuickOptionSelect(option)}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
