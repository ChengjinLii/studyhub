interface FilterToggleButtonProps {
  expanded: boolean;
  activeFilterCount?: number;
  className?: string;
  onClick: () => void;
}

export default function FilterToggleButton({
  expanded,
  activeFilterCount = 0,
  className = '',
  onClick,
}: FilterToggleButtonProps) {
  const actionLabel = expanded ? '收起高级筛选' : '更多筛选';
  const accessibleLabel =
    activeFilterCount > 0 ? `${actionLabel}，已启用 ${activeFilterCount} 项条件` : actionLabel;

  return (
    <button
      type="button"
      className={`button ghost filter-toggle-button${expanded ? ' is-active' : ''}${className ? ` ${className}` : ''}`}
      onClick={onClick}
      aria-label={accessibleLabel}
      aria-expanded={expanded}
      title={actionLabel}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 6h10" />
        <path d="M18 6h2" />
        <circle cx="16" cy="6" r="2" />
        <path d="M4 12h2" />
        <path d="M10 12h10" />
        <circle cx="8" cy="12" r="2" />
        <path d="M4 18h7" />
        <path d="M15 18h5" />
        <circle cx="13" cy="18" r="2" />
      </svg>
      {activeFilterCount > 0 ? (
        <span className="filter-toggle-button__badge" aria-hidden="true">
          {activeFilterCount}
        </span>
      ) : null}
    </button>
  );
}
