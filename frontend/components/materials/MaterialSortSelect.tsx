import { MATERIAL_SORT_OPTIONS, normalizeMaterialSort } from '../../constants/materialSort';

interface MaterialSortSelectProps {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}

export default function MaterialSortSelect({ value, disabled, onChange }: MaterialSortSelectProps) {
  return (
    <label className="material-sort-control">
      <span>排序方式</span>
      <select
        value={normalizeMaterialSort(value)}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        aria-label="资料排序方式"
      >
        {MATERIAL_SORT_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
