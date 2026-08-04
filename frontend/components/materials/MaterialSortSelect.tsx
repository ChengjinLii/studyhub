import { KeyboardEvent, useEffect, useId, useRef, useState } from 'react';
import { MATERIAL_SORT_OPTIONS, normalizeMaterialSort } from '../../constants/materialSort';

interface MaterialSortSelectProps {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}

export default function MaterialSortSelect({ value, disabled, onChange }: MaterialSortSelectProps) {
  const normalizedValue = normalizeMaterialSort(value);
  const selectedIndex = MATERIAL_SORT_OPTIONS.findIndex((option) => option.value === normalizedValue);
  const selectedOption = MATERIAL_SORT_OPTIONS[selectedIndex];
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxId = useId();

  useEffect(() => {
    setActiveIndex(selectedIndex);
  }, [selectedIndex]);

  useEffect(() => {
    if (!open) return undefined;
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const chooseOption = (index: number) => {
    const option = MATERIAL_SORT_OPTIONS[index];
    if (!option) return;
    setOpen(false);
    setActiveIndex(index);
    if (option.value !== normalizedValue) onChange(option.value);
    triggerRef.current?.focus();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    if (event.key === 'Escape') {
      if (open) {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
      return;
    }
    if (event.key === 'Tab') {
      setOpen(false);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      setOpen(true);
      setActiveIndex((current) => (current + direction + MATERIAL_SORT_OPTIONS.length) % MATERIAL_SORT_OPTIONS.length);
      return;
    }
    if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      setOpen(true);
      setActiveIndex(event.key === 'Home' ? 0 : MATERIAL_SORT_OPTIONS.length - 1);
      return;
    }
    if ((event.key === 'Enter' || event.key === ' ') && open) {
      event.preventDefault();
      chooseOption(activeIndex);
    }
  };

  return (
    <div className={`material-sort-control ${open ? 'is-open' : ''}`} ref={rootRef} onKeyDown={handleKeyDown}>
      <span className="material-sort-label">排序方式</span>
      <button
        ref={triggerRef}
        className="material-sort-trigger"
        type="button"
        disabled={disabled}
        aria-label="资料排序方式"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        onClick={() => {
          setActiveIndex(selectedIndex);
          setOpen((current) => !current);
        }}
      >
        <span>{selectedOption.label}</span>
        <span className="material-sort-trigger__chevron" aria-hidden="true">⌄</span>
      </button>
      {open && (
        <div className="material-sort-options" id={listboxId} role="listbox" aria-label="选择资料排序方式">
          {MATERIAL_SORT_OPTIONS.map((option, index) => {
            const selected = option.value === normalizedValue;
            return (
              <button
                key={option.value}
                id={`${listboxId}-${index}`}
                className={`material-sort-option ${activeIndex === index ? 'is-active' : ''}`}
                type="button"
                role="option"
                aria-selected={selected}
                tabIndex={-1}
                onPointerEnter={() => setActiveIndex(index)}
                onClick={() => chooseOption(index)}
              >
                <span>{option.label}</span>
                <span className="material-sort-option__check" aria-hidden="true">✓</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
