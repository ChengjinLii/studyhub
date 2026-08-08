import { UploadSectionStatus } from '../../lib/uploadSectionCompletion';

interface UploadNavigationItem {
  id: string;
  label: string;
}

interface UploadProgressSidebarProps {
  items: UploadNavigationItem[];
  activeSection: string;
  completion: Record<string, UploadSectionStatus>;
  onJump: (sectionId: string) => void;
}

export default function UploadProgressSidebar({
  items,
  activeSection,
  completion,
  onJump,
}: UploadProgressSidebarProps) {
  return (
    <aside className="me-sidebar upload-sidebar">
      <div className="me-sidebar__brand">投稿中心</div>
      <div className="me-sidebar__group">
        <div className="me-sidebar__label">页面导航</div>
        <nav className="me-sidebar__items" aria-label="投稿页面导航">
          {items.map((item, index) => {
            const status = completion[item.id] || { complete: false, missing: [] };
            const statusText = status.complete
              ? `${item.label}已完成`
              : status.missing.length > 0
                ? `还需填写：${status.missing.join('、')}`
                : `${item.label}待完善`;
            return (
              <a
                key={item.id}
                href={`#${item.id}`}
                className={`me-sidebar__item${activeSection === item.id ? ' active' : ''}${
                  status.complete ? ' is-complete' : ''
                }`}
                aria-current={activeSection === item.id ? 'location' : undefined}
                onClick={(event) => {
                  event.preventDefault();
                  onJump(item.id);
                }}
              >
                <span className="me-sidebar__indicator" />
                <span className="me-sidebar__index">{String(index + 1).padStart(2, '0')}</span>
                <span className="me-sidebar__text">{item.label}</span>
                <span
                  className="upload-sidebar__completion"
                  role="img"
                  aria-label={statusText}
                >
                  {status.complete ? '✓' : ''}
                  <span className="upload-sidebar__completion-tooltip" role="tooltip">
                    {statusText}
                  </span>
                </span>
              </a>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
