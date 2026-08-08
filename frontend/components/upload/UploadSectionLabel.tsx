interface UploadSectionLabelProps {
  text: string;
  htmlFor?: string;
  optional?: boolean;
  selectionHint?: string;
}

export default function UploadSectionLabel({ text, htmlFor, optional, selectionHint }: UploadSectionLabelProps) {
  return (
    <label htmlFor={htmlFor} className="section-label">
      <span className="section-marker" aria-hidden="true" />
      <span>{text}</span>
      {optional && <span className="optional-pill">可选</span>}
      {selectionHint && <span className="selection-hint-pill">{selectionHint}</span>}
    </label>
  );
}
