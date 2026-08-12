interface MaterialSearchEmptyProps {
  loading?: boolean;
  onReset: () => void;
  onEditKeyword: () => void;
}

export default function MaterialSearchEmpty({ loading = false, onReset, onEditKeyword }: MaterialSearchEmptyProps) {
  return (
    <div className="empty-state material-search-empty">
      <strong>暂未找到符合条件的资料</strong>
      <span>可以减少关键词、清除筛选，或改用课程简称和资料类型重新搜索。</span>
      <div className="material-search-empty__actions">
        <button className="button ghost small" type="button" onClick={onReset} disabled={loading}>
          重置条件
        </button>
        <button className="button primary small" type="button" onClick={onEditKeyword}>
          修改关键词
        </button>
      </div>
    </div>
  );
}
