import { useState } from 'react';

interface StarRatingProps {
  value: number;
  onChange?: (value: number) => void;
  readOnly?: boolean;
  size?: number;
}

export default function StarRating({ value, onChange, readOnly, size = 28 }: StarRatingProps) {
  const [hover, setHover] = useState<number | null>(null);
  const displayValue = hover ?? value;

  const handleSelect = (score: number) => {
    if (readOnly || !onChange) return;
    onChange(score);
  };

  return (
    <div className="star-rating" role="radiogroup" aria-label="评分">
      {[1, 2, 3, 4, 5].map((score) => {
        const active = displayValue >= score;
        return (
          <button
            key={score}
            type="button"
            className={active ? 'star active' : 'star'}
            onClick={() => handleSelect(score)}
            onMouseEnter={() => !readOnly && setHover(score)}
            onMouseLeave={() => !readOnly && setHover(null)}
            aria-label={`评分 ${score}`}
            aria-checked={value === score}
            role="radio"
          >
            ★
          </button>
        );
      })}
      <style jsx>{`
        .star-rating {
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }
        .star {
          font-size: ${size}px;
          line-height: 1;
          background: none;
          border: none;
          cursor: ${readOnly ? 'default' : 'pointer'};
          color: var(--border-strong);
          padding: 0;
        }
        .star.active {
          color: var(--warning);
        }
        .star:focus-visible {
          outline: 2px solid var(--brand-primary);
          border-radius: 4px;
        }
        @media (hover: none) {
          .star {
            color: ${readOnly ? 'var(--border-strong)' : 'inherit'};
          }
        }
      `}</style>
    </div>
  );
}
