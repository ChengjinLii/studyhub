interface UploadChoiceCardProps {
  name: string;
  value: string;
  title: string;
  description: string;
  selected: boolean;
  onSelect: () => void;
}

export default function UploadChoiceCard({
  name,
  value,
  title,
  description,
  selected,
  onSelect,
}: UploadChoiceCardProps) {
  return (
    <label className={`upload-choice-card${selected ? ' is-selected' : ''}`}>
      <input type="radio" name={name} value={value} checked={selected} onChange={onSelect} />
      <span className="upload-choice-card__radio" aria-hidden="true">
        <span />
      </span>
      <span className="upload-choice-card__copy">
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
      <span className="upload-choice-card__state">{selected ? '已选择' : '选择'}</span>
    </label>
  );
}
