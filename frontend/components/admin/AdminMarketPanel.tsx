import { FormEvent } from 'react';
import AppImage from '../AppImage';
import PaginationBar from '../PaginationBar';
import { MarketBatchFormState, MarketBatchUpdatePayload } from '../../lib/adminBatchPayloads';
import { formatDateTime } from '../../lib/format';
import { AdminMarketItem } from '../../types/admin';

type AlertMessage = { type: 'success' | 'error'; text: string } | null;

const MARKET_CATEGORY_OPTIONS = [
  { value: 'BOOK', label: '书籍' },
  { value: 'DIGITAL', label: '数码' },
  { value: 'LIFE', label: '日用品' },
  { value: 'SPORT', label: '运动' },
  { value: 'OTHER', label: '其他' },
];

const MARKET_STATUS_OPTIONS = [
  { value: 'SALE', label: '在售' },
  { value: 'RESERVED', label: '已预定' },
  { value: 'SOLD', label: '已售出' },
  { value: 'REMOVED', label: '已下架' },
  { value: 'HIDDEN', label: '隐藏（不展示）' },
];

const MARKET_CONTACT_OPTIONS = [
  { value: 'QQ', label: 'QQ' },
  { value: 'WECHAT', label: '微信' },
  { value: 'PHONE', label: '手机号' },
];

interface AdminMarketPanelProps {
  marketItems: AdminMarketItem[];
  marketLoading: boolean;
  selectedMarketIds: number[];
  marketBatchMessage: AlertMessage;
  marketBatchDeleting: boolean;
  marketBatchForm: MarketBatchFormState;
  currentMarketPage: number;
  marketTotalItems: number;
  marketPageSize: number;
  onRefresh: () => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onApplyMarketBatchUpdate: (payload: MarketBatchUpdatePayload, actionLabel?: string) => void;
  onMarketBatchDelete: () => void;
  onToggleSelection: (id: number) => void;
  onPageChange: (page: number) => void;
  onMarketBatchSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onMarketBatchInputChange: (field: keyof MarketBatchFormState, value: string) => void;
}

export default function AdminMarketPanel({
  marketItems,
  marketLoading,
  selectedMarketIds,
  marketBatchMessage,
  marketBatchDeleting,
  marketBatchForm,
  currentMarketPage,
  marketTotalItems,
  marketPageSize,
  onRefresh,
  onSelectAll,
  onClearSelection,
  onApplyMarketBatchUpdate,
  onMarketBatchDelete,
  onToggleSelection,
  onPageChange,
  onMarketBatchSubmit,
  onMarketBatchInputChange,
}: AdminMarketPanelProps) {
  return (
    <section id="admin-market" className="card admin-section">
      <div className="card-title">校园集市商品批量管理</div>
      <p className="help-text">
        勾选商品后，可批量调整状态、分类、学校或联系方式；隐藏商品将不在前台展示，可随时恢复展示。
      </p>
      <div className="inline-group wrap" style={{ marginBottom: 12 }}>
        <button className="button ghost small" type="button" onClick={onRefresh} disabled={marketLoading}>
          {marketLoading ? '刷新中...' : '刷新商品列表'}
        </button>
        <button className="button ghost small" type="button" onClick={onSelectAll}>
          全选当前页
        </button>
        <button className="button ghost small" type="button" onClick={onClearSelection}>
          清空选择
        </button>
        <button
          className="button ghost small"
          type="button"
          onClick={() => onApplyMarketBatchUpdate({ itemIds: selectedMarketIds, status: 'HIDDEN' }, '隐藏所选')}
          disabled={marketLoading || selectedMarketIds.length === 0}
        >
          隐藏所选
        </button>
        <button
          className="button ghost small"
          type="button"
          onClick={() => onApplyMarketBatchUpdate({ itemIds: selectedMarketIds, status: 'SALE' }, '恢复展示')}
          disabled={marketLoading || selectedMarketIds.length === 0}
        >
          恢复展示
        </button>
        <button
          className="button danger small"
          type="button"
          onClick={onMarketBatchDelete}
          disabled={marketBatchDeleting || selectedMarketIds.length === 0}
        >
          {marketBatchDeleting ? '删除中...' : '删除所选'}
        </button>
        <span className="help-text">已选 {selectedMarketIds.length} 条</span>
      </div>
      {marketBatchMessage && (
        <p className={marketBatchMessage.type === 'error' ? 'error-text' : 'success-text'}>{marketBatchMessage.text}</p>
      )}
      {marketItems.length === 0 ? (
        <p className="help-text">暂无校园集市商品</p>
      ) : (
        <ul className="materials-list" style={{ alignItems: 'flex-start' }}>
          {marketItems.map((item) => (
            <li key={item.id} className="purchase-row">
              <label className="checkbox" style={{ marginRight: 12 }}>
                <input
                  type="checkbox"
                  checked={selectedMarketIds.includes(item.id)}
                  onChange={() => onToggleSelection(item.id)}
                />
              </label>
              <div className="market-admin-entry">
                <div className="inline-group" style={{ alignItems: 'flex-start', gap: 16 }}>
                  {item.thumbnail ? (
                    <AppImage
                      src={item.thumbnail}
                      alt={item.title}
                      style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 8 }}
                    />
                  ) : (
                    <div
                      style={{
                        width: 72,
                        height: 72,
                        borderRadius: 8,
                        background: '#f5f5f5',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 12,
                        color: '#666',
                      }}
                    >
                      无图
                    </div>
                  )}
                  <div>
                    <strong>{item.title}</strong>
                    <p className="material-meta">
                      {item.priceText || `¥${item.price?.toFixed(2) ?? '--'}`} · 分类：
                      {MARKET_CATEGORY_OPTIONS.find((opt) => opt.value === item.category)?.label || item.category || '未分类'} · 状态：
                      {MARKET_STATUS_OPTIONS.find((opt) => opt.value === item.status)?.label || item.status || '未知'}
                    </p>
                    <p className="material-meta">
                      想要人数：{item.wantCount ?? 0} · 学校：{item.school || '不限'} · 发布者：
                      {item.sellerName || '未知'} ({item.sellerId ? `#${item.sellerId}` : '—'}) ·
                      {item.createdAt ? `发布时间：${formatDateTime(item.createdAt)}` : '发布时间未知'}
                    </p>
                    <p className="material-meta">
                      联系方式：{item.contactType ? `${item.contactType} · ${item.contactValue || '未填写'}` : '未填写'}
                    </p>
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <PaginationBar
        currentPage={currentMarketPage}
        totalItems={marketTotalItems}
        pageSize={marketPageSize}
        loading={marketLoading}
        onPageChange={onPageChange}
        className="admin-pagination"
      />
      <form className="form-grid" onSubmit={onMarketBatchSubmit}>
        <div className="form-item">
          <label htmlFor="market-status">状态</label>
          <select
            id="market-status"
            value={marketBatchForm.status}
            onChange={(e) => onMarketBatchInputChange('status', e.target.value)}
          >
            <option value="">保持不变</option>
            {MARKET_STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-item">
          <label htmlFor="market-category">分类</label>
          <select
            id="market-category"
            value={marketBatchForm.category}
            onChange={(e) => onMarketBatchInputChange('category', e.target.value)}
          >
            <option value="">保持不变</option>
            {MARKET_CATEGORY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-item">
          <label htmlFor="market-school">学校</label>
          <input
            id="market-school"
            value={marketBatchForm.school}
            placeholder="保持为空则不变"
            onChange={(e) => onMarketBatchInputChange('school', e.target.value)}
          />
        </div>
        <div className="form-item">
          <label htmlFor="market-contact-type">联系方式类型</label>
          <select
            id="market-contact-type"
            value={marketBatchForm.contactType}
            onChange={(e) => onMarketBatchInputChange('contactType', e.target.value)}
          >
            <option value="">保持不变</option>
            {MARKET_CONTACT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-item">
          <label htmlFor="market-contact-value">联系方式内容</label>
          <input
            id="market-contact-value"
            value={marketBatchForm.contactValue}
            placeholder="保持为空则不变"
            onChange={(e) => onMarketBatchInputChange('contactValue', e.target.value)}
          />
        </div>
        <div className="form-item full">
          <button className="button primary" type="submit" disabled={marketLoading}>
            批量更新（已选 {selectedMarketIds.length} 条）
          </button>
        </div>
      </form>
    </section>
  );
}
