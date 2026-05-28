import { FormEvent } from 'react';
import PaginationBar from '../PaginationBar';
import { COURSE_CATEGORY_LABELS, COURSE_CATEGORY_OPTIONS, GRADE_STAGE_OPTIONS, SUPPORTED_COLLEGES, SUPPORTED_MAJORS } from '../../constants/metadata';
import { MaterialBatchFormState } from '../../lib/adminBatchPayloads';
import { formatDateTime } from '../../lib/format';
import { formatMajorDisplay } from '../../lib/major';
import { AdminMaterial } from '../../types/admin';

type AlertMessage = { type: 'success' | 'error'; text: string } | null;

interface AdminMaterialsPanelProps {
  materials: AdminMaterial[];
  materialView: 'active' | 'removed';
  materialsLoading: boolean;
  batchMessage: AlertMessage;
  selectedMaterialIds: number[];
  batchDeleting: boolean;
  batchRestoring: boolean;
  restoringMaterialId: number | null;
  currentMaterialPage: number;
  materialTotalItems: number;
  materialPageSize: number;
  batchForm: MaterialBatchFormState;
  batchMajorSelections: string[];
  onRefresh: () => void;
  onViewChange: (view: 'active' | 'removed') => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onBatchRestore: () => void;
  onBatchDelete: () => void;
  onToggleSelection: (id: number) => void;
  onRestoreMaterial: (id: number) => void;
  onPageChange: (page: number) => void;
  onBatchSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onBatchInputChange: (field: keyof MaterialBatchFormState, value: string) => void;
  onBatchMajorToggle: (major: string, checked: boolean) => void;
}

export default function AdminMaterialsPanel({
  materials,
  materialView,
  materialsLoading,
  batchMessage,
  selectedMaterialIds,
  batchDeleting,
  batchRestoring,
  restoringMaterialId,
  currentMaterialPage,
  materialTotalItems,
  materialPageSize,
  batchForm,
  batchMajorSelections,
  onRefresh,
  onViewChange,
  onSelectAll,
  onClearSelection,
  onBatchRestore,
  onBatchDelete,
  onToggleSelection,
  onRestoreMaterial,
  onPageChange,
  onBatchSubmit,
  onBatchInputChange,
  onBatchMajorToggle,
}: AdminMaterialsPanelProps) {
  const isRemovedMaterialView = materialView === 'removed';
  const resolveCourseCategoryLabel = (value?: string | null) => {
    if (!value) return '未分类';
    return COURSE_CATEGORY_LABELS[value as keyof typeof COURSE_CATEGORY_LABELS] || value;
  };

  return (
    <section id="admin-materials" className="card admin-section">
      <div className="card-title">资料批量管理</div>
      <p className="help-text">
        {isRemovedMaterialView
          ? '展示最近删除的资料，可逐一或批量恢复。'
          : '勾选资料后，可一次性调整专业、年级、课程类型、标签，或批量删除。'}
      </p>
      <div className="inline-group wrap" style={{ marginBottom: 12 }}>
        <button className="button ghost small" type="button" onClick={onRefresh} disabled={materialsLoading}>
          {materialsLoading ? '刷新中...' : '刷新列表'}
        </button>
        <button
          className="button ghost small"
          type="button"
          onClick={() => onViewChange(isRemovedMaterialView ? 'active' : 'removed')}
          disabled={materialsLoading}
        >
          {isRemovedMaterialView ? '查看正常资料' : '查看已删除'}
        </button>
        <button className="button ghost small" type="button" onClick={onSelectAll}>
          全选当前页
        </button>
        <button className="button ghost small" type="button" onClick={onClearSelection}>
          清空选择
        </button>
        {isRemovedMaterialView ? (
          <button
            className="button ghost small"
            type="button"
            onClick={onBatchRestore}
            disabled={batchRestoring || selectedMaterialIds.length === 0}
          >
            {batchRestoring ? '恢复中...' : '恢复所选'}
          </button>
        ) : (
          <button
            className="button danger small"
            type="button"
            onClick={onBatchDelete}
            disabled={batchDeleting || selectedMaterialIds.length === 0}
          >
            {batchDeleting ? '删除中...' : '删除所选'}
          </button>
        )}
        <span className="help-text">已选 {selectedMaterialIds.length} 条</span>
      </div>
      {batchMessage && (
        <p className={batchMessage.type === 'error' ? 'error-text' : 'success-text'}>{batchMessage.text}</p>
      )}
      {materials.length === 0 ? (
        <p className="help-text">暂无资料</p>
      ) : (
        <ul className="materials-list" style={{ alignItems: 'flex-start' }}>
          {materials.map((material) => {
            const majorLabel = formatMajorDisplay(material.major);
            return (
              <li key={material.id} className="purchase-row">
                <label className="checkbox" style={{ marginRight: 12 }}>
                  <input
                    type="checkbox"
                    checked={selectedMaterialIds.includes(material.id)}
                    onChange={() => onToggleSelection(material.id)}
                  />
                </label>
                <div>
                  <strong>{material.title}</strong>
                  <p className="material-meta">
                    {resolveCourseCategoryLabel(material.courseCategory)} · {material.gradeValue || '未设置'} ·{' '}
                    {material.college || '未设置'} {majorLabel || ''}
                  </p>
                  {material.tags && material.tags.length > 0 && (
                    <p className="material-meta">标签：{material.tags.join(' / ')}</p>
                  )}
                  <p className="material-meta">
                    上传者：{material.uploaderNickname || material.uploaderUsername || '匿名'} ·{' '}
                    {formatDateTime(material.createdAt) || '-'}
                  </p>
                  {isRemovedMaterialView && (
                    <p className="material-meta">
                      状态：已删除
                      {material.deletedAt ? ` · 删除时间：${formatDateTime(material.deletedAt)}` : ''}
                    </p>
                  )}
                </div>
                {isRemovedMaterialView && (
                  <button
                    className="button ghost small"
                    type="button"
                    onClick={() => onRestoreMaterial(material.id)}
                    disabled={restoringMaterialId === material.id}
                    style={{ marginLeft: 'auto' }}
                  >
                    {restoringMaterialId === material.id ? '恢复中...' : '恢复'}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <PaginationBar
        currentPage={currentMaterialPage}
        totalItems={materialTotalItems}
        pageSize={materialPageSize}
        loading={materialsLoading}
        onPageChange={onPageChange}
        className="admin-pagination"
      />
      <form className="form-grid" onSubmit={onBatchSubmit}>
        <div className="form-item">
          <label htmlFor="batch-college">学院</label>
          <select
            id="batch-college"
            value={batchForm.college}
            onChange={(e) => onBatchInputChange('college', e.target.value)}
          >
            <option value="">保持不变</option>
            {SUPPORTED_COLLEGES.map((college) => (
              <option key={college} value={college}>
                {college}
              </option>
            ))}
          </select>
        </div>
        <div className="form-item">
          <label>专业（多选）</label>
          <div className="inline-group wrap">
            {SUPPORTED_MAJORS.map((major) => (
              <label key={major} className={`choice badge-outline ${batchMajorSelections.includes(major) ? 'active' : ''}`}>
                <input
                  type="checkbox"
                  checked={batchMajorSelections.includes(major)}
                  onChange={(e) => onBatchMajorToggle(major, e.target.checked)}
                />
                {major}
              </label>
            ))}
          </div>
          <div className="inline-group wrap" style={{ marginTop: 6 }}>
            <button
              className="button ghost small"
              type="button"
              onClick={() => onBatchInputChange('major', '')}
              disabled={!batchForm.major}
            >
              {batchForm.major ? '清空选择（保持不变）' : '保持不变'}
            </button>
          </div>
        </div>
        <div className="form-item">
          <label htmlFor="batch-grade">年级/阶段</label>
          <select
            id="batch-grade"
            value={batchForm.gradeValue}
            onChange={(e) => onBatchInputChange('gradeValue', e.target.value)}
          >
            <option value="">保持不变</option>
            {GRADE_STAGE_OPTIONS.map((grade) => (
              <option key={grade} value={grade}>
                {grade}
              </option>
            ))}
          </select>
        </div>
        <div className="form-item">
          <label htmlFor="batch-course-category">课程类型</label>
          <select
            id="batch-course-category"
            value={batchForm.courseCategory}
            onChange={(e) => onBatchInputChange('courseCategory', e.target.value)}
          >
            <option value="">保持不变</option>
            {COURSE_CATEGORY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-item full">
          <label htmlFor="batch-tags">标签（逗号分隔）</label>
          <input
            id="batch-tags"
            type="text"
            placeholder="示例：期末速成,教材答案"
            value={batchForm.tags}
            onChange={(e) => onBatchInputChange('tags', e.target.value)}
          />
          {batchForm.tags && (
            <div className="inline-group" style={{ marginTop: 6 }}>
              <label className="checkbox">
                <input
                  type="radio"
                  name="tags-mode"
                  value="replace"
                  checked={batchForm.tagsMode === 'replace'}
                  onChange={(e) => onBatchInputChange('tagsMode', e.target.value)}
                />
                覆盖
              </label>
              <label className="checkbox">
                <input
                  type="radio"
                  name="tags-mode"
                  value="append"
                  checked={batchForm.tagsMode === 'append'}
                  onChange={(e) => onBatchInputChange('tagsMode', e.target.value)}
                />
                追加
              </label>
            </div>
          )}
        </div>
        <div className="form-item full">
          <button className="button primary" type="submit" disabled={materialsLoading}>
            批量更新（已选 {selectedMaterialIds.length} 条）
          </button>
        </div>
      </form>
    </section>
  );
}
