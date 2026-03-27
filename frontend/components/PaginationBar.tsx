import React, { useMemo } from 'react';

const DOTS_LEFT = 'DOTS_LEFT';
const DOTS_RIGHT = 'DOTS_RIGHT';

const buildNumberRange = (start: number, end: number) => {
  if (end < start) {
    return [];
  }
  return Array.from({ length: end - start + 1 }, (_, idx) => start + idx);
};

export interface PaginationBarProps {
  currentPage: number;
  totalItems: number;
  pageSize: number;
  loading?: boolean;
  onPageChange: (page: number) => void;
  className?: string;
}

export const PaginationBar: React.FC<PaginationBarProps> = ({
  currentPage,
  totalItems,
  pageSize,
  loading = false,
  onPageChange,
  className = 'materials-pagination',
}) => {
  const safePageSize = Math.max(pageSize, 1);
  const totalPages = Math.max(1, Math.ceil((totalItems || 0) / safePageSize));
  const startItem = totalItems === 0 ? 0 : (currentPage - 1) * safePageSize + 1;
  const endItem = totalItems === 0 ? 0 : Math.min(startItem + safePageSize - 1, totalItems);

  const paginationRange = useMemo(() => {
    if (totalPages <= 5) {
      return buildNumberRange(1, totalPages);
    }
    const siblingCount = 1;
    const leftSibling = Math.max(currentPage - siblingCount, 2);
    const rightSibling = Math.min(currentPage + siblingCount, totalPages - 1);
    const showLeftDots = leftSibling > 2;
    const showRightDots = rightSibling < totalPages - 1;
    const range: Array<number | string> = [1];
    if (showLeftDots) {
      range.push(DOTS_LEFT);
    } else {
      range.push(...buildNumberRange(2, leftSibling - 1));
    }
    range.push(...buildNumberRange(leftSibling, rightSibling));
    if (showRightDots) {
      range.push(DOTS_RIGHT);
    } else {
      range.push(...buildNumberRange(rightSibling + 1, totalPages - 1));
    }
    range.push(totalPages);
    return range;
  }, [currentPage, totalPages]);

  const handleChange = (nextPage: number) => {
    if (loading) return;
    if (nextPage < 1 || nextPage > totalPages || nextPage === currentPage) return;
    onPageChange(nextPage);
  };

  return (
    <div className={className}>
      <p className="pagination-summary">
        显示第 {startItem} - {endItem} 条，共 {totalItems} 条
      </p>
      <div className="pagination-controls">
        <button
          type="button"
          className="pagination-button"
          onClick={() => handleChange(currentPage - 1)}
          disabled={loading || currentPage <= 1}
          aria-label="上一页"
        >
          上一页
        </button>
        {paginationRange.map((item, index) => {
          if (item === DOTS_LEFT || item === DOTS_RIGHT) {
            return (
              <span key={`dots-${index}`} className="pagination-ellipsis" aria-hidden="true">
                …
              </span>
            );
          }
          const pageNumber = Number(item);
          const isActive = pageNumber === currentPage;
          return (
            <button
              key={`page-${pageNumber}`}
              type="button"
              className={`pagination-button ${isActive ? 'active' : ''}`}
              aria-label={`第 ${pageNumber} 页`}
              aria-current={isActive ? 'page' : undefined}
              disabled={loading || isActive}
              onClick={() => handleChange(pageNumber)}
            >
              {pageNumber}
            </button>
          );
        })}
        <button
          type="button"
          className="pagination-button"
          onClick={() => handleChange(currentPage + 1)}
          disabled={loading || currentPage >= totalPages}
          aria-label="下一页"
        >
          下一页
        </button>
      </div>
    </div>
  );
};

export default PaginationBar;
