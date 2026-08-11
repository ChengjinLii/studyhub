interface SearchIconButtonProps {
  disabled?: boolean;
  label?: string;
}

export default function SearchIconButton({
  disabled = false,
  label = '搜索资料',
}: SearchIconButtonProps) {
  return (
    <button
      className="button primary search-icon-button"
      type="submit"
      disabled={disabled}
      aria-label={disabled ? '正在搜索资料' : label}
      title={label}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="10.75" cy="10.75" r="6.75" />
        <path d="m15.75 15.75 4.25 4.25" />
      </svg>
    </button>
  );
}
