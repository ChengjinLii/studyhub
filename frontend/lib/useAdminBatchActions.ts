import { FormEvent, useState } from 'react';
import {
  buildMarketBatchUpdatePayload,
  buildMaterialBatchUpdatePayload,
  type MarketBatchFormState,
  type MaterialBatchFormState,
} from './adminBatchPayloads';
import { fetchBackend } from './apiBase';
import { toErrorMessage } from './errors';
import { parseMajorList, serializeMajorList } from './major';
import { AdminMaterial, AdminMarketItem } from '../types/admin';

type AlertMessage = { type: 'success' | 'error'; text: string } | null;

interface UseAdminBatchActionsOptions {
  materials: AdminMaterial[];
  marketItems: AdminMarketItem[];
  materialView: 'active' | 'removed';
  currentMaterialPage: number;
  currentMarketPage: number;
  loadMaterials: (page?: number, view?: 'active' | 'removed') => Promise<void> | void;
  loadMarketItems: (page?: number) => Promise<void> | void;
}

export const useAdminBatchActions = ({
  materials,
  marketItems,
  materialView,
  currentMaterialPage,
  currentMarketPage,
  loadMaterials,
  loadMarketItems,
}: UseAdminBatchActionsOptions) => {
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<number[]>([]);
  const [selectedMarketIds, setSelectedMarketIds] = useState<number[]>([]);
  const [batchForm, setBatchForm] = useState<MaterialBatchFormState>({
    college: '',
    major: '',
    gradeValue: '',
    courseCategory: '',
    tags: '',
    tagsMode: 'replace',
  });
  const [batchMessage, setBatchMessage] = useState<AlertMessage>(null);
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [batchRestoring, setBatchRestoring] = useState(false);
  const [marketBatchForm, setMarketBatchForm] = useState<MarketBatchFormState>({
    status: '',
    category: '',
    school: '',
    contactType: '',
    contactValue: '',
  });
  const [marketBatchMessage, setMarketBatchMessage] = useState<AlertMessage>(null);
  const [marketBatchDeleting, setMarketBatchDeleting] = useState(false);

  const batchMajorSelections = parseMajorList(batchForm.major);

  const toggleMaterialSelection = (id: number) => {
    setSelectedMaterialIds((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));
  };

  const selectAllMaterials = () => {
    setSelectedMaterialIds(materials.map((item) => item.id));
  };

  const clearMaterialSelection = () => {
    setSelectedMaterialIds([]);
  };

  const toggleMarketSelection = (id: number) => {
    setSelectedMarketIds((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));
  };

  const selectAllMarketItems = () => {
    setSelectedMarketIds(marketItems.map((item) => item.id));
  };

  const clearMarketSelection = () => {
    setSelectedMarketIds([]);
  };

  const handleBatchInputChange = (field: keyof MaterialBatchFormState, value: string) => {
    setBatchForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleBatchMajorToggle = (value: string, checked: boolean) => {
    setBatchForm((prev) => {
      const current = parseMajorList(prev.major);
      let next: string[];
      if (checked) {
        next = current.includes(value) ? current : [...current, value];
      } else {
        next = current.filter((item) => item !== value);
      }
      return { ...prev, major: serializeMajorList(next) };
    });
  };

  const handleMarketBatchInputChange = (field: keyof MarketBatchFormState, value: string) => {
    setMarketBatchForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleBatchSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (selectedMaterialIds.length === 0) {
      setBatchMessage({ type: 'error', text: '请先选择至少一条资料' });
      return;
    }
    const payload = buildMaterialBatchUpdatePayload(selectedMaterialIds, batchForm);
    setBatchMessage(null);
    try {
      const resp = await fetchBackend('/admin/materials/batch-update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '批量更新失败');
      }
      const updatedCount = json.data?.updated ?? selectedMaterialIds.length;
      const missingCount = Array.isArray(json.data?.missingIds) ? json.data.missingIds.length : 0;
      setBatchMessage({
        type: 'success',
        text: `已更新 ${updatedCount} 条资料${missingCount ? `，其中 ${missingCount} 条未找到` : ''}`,
      });
      setSelectedMaterialIds([]);
      await Promise.resolve(loadMaterials(currentMaterialPage - 1, materialView));
    } catch (err: unknown) {
      setBatchMessage({ type: 'error', text: toErrorMessage(err, '批量更新失败') });
    }
  };

  const handleBatchDelete = async () => {
    if (selectedMaterialIds.length === 0) {
      setBatchMessage({ type: 'error', text: '请先选择至少一条资料' });
      return;
    }
    if (!window.confirm(`确定删除选中的 ${selectedMaterialIds.length} 条资料？管理员可在后台恢复。`)) {
      return;
    }
    setBatchDeleting(true);
    setBatchMessage(null);
    try {
      const resp = await fetchBackend('/admin/materials/batch-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ materialIds: selectedMaterialIds }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '批量删除失败');
      }
      const deleted = json.data?.deleted ?? 0;
      const failedIds: number[] = Array.isArray(json.data?.failedIds) ? json.data.failedIds : [];
      let text = `已删除 ${deleted} 条资料。`;
      if (failedIds.length) {
        text += ` ${failedIds.length} 条删除失败：${failedIds.join(', ')}`;
      }
      setBatchMessage({
        type: failedIds.length ? 'error' : 'success',
        text,
      });
      setSelectedMaterialIds(failedIds);
      await Promise.resolve(loadMaterials(currentMaterialPage - 1, materialView));
    } catch (err: unknown) {
      setBatchMessage({ type: 'error', text: toErrorMessage(err, '批量删除失败') });
    } finally {
      setBatchDeleting(false);
    }
  };

  const handleBatchRestore = async () => {
    if (selectedMaterialIds.length === 0) {
      setBatchMessage({ type: 'error', text: '请先选择至少一条资料' });
      return;
    }
    if (!window.confirm(`确定恢复选中的 ${selectedMaterialIds.length} 条资料？`)) {
      return;
    }
    setBatchRestoring(true);
    setBatchMessage(null);
    try {
      const resp = await fetchBackend('/admin/materials/batch-restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ materialIds: selectedMaterialIds }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '批量恢复失败');
      }
      const restored = json.data?.restored ?? 0;
      const failedIds: number[] = Array.isArray(json.data?.failedIds) ? json.data.failedIds : [];
      let text = `已恢复 ${restored} 条资料。`;
      if (failedIds.length) {
        text += ` ${failedIds.length} 条恢复失败：${failedIds.join(', ')}`;
      }
      setBatchMessage({
        type: failedIds.length ? 'error' : 'success',
        text,
      });
      setSelectedMaterialIds(failedIds);
      await Promise.resolve(loadMaterials(currentMaterialPage - 1, 'removed'));
    } catch (err: unknown) {
      setBatchMessage({ type: 'error', text: toErrorMessage(err, '批量恢复失败') });
    } finally {
      setBatchRestoring(false);
    }
  };

  const applyMarketBatchUpdate = async (
    payload: ReturnType<typeof buildMarketBatchUpdatePayload>,
    actionLabel?: string
  ) => {
    if (selectedMarketIds.length === 0) {
      setMarketBatchMessage({ type: 'error', text: '请先选择至少一条商品' });
      return;
    }
    if (!payload || Object.keys(payload).length === 1) {
      setMarketBatchMessage({ type: 'error', text: '请至少填写一个需要更新的字段' });
      return;
    }
    setMarketBatchMessage(null);
    try {
      const resp = await fetchBackend('/admin/market/batch-update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '批量更新失败');
      }
      const updated = json.data?.updated ?? selectedMarketIds.length;
      const missingIds: number[] = Array.isArray(json.data?.missingIds) ? json.data.missingIds : [];
      const prefix = actionLabel ? `${actionLabel}：` : '';
      setMarketBatchMessage({
        type: missingIds.length ? 'error' : 'success',
        text: `${prefix}已更新 ${updated} 条商品${missingIds.length ? `，${missingIds.length} 条未找到` : ''}`,
      });
      setSelectedMarketIds(missingIds);
      await Promise.resolve(loadMarketItems(currentMarketPage));
    } catch (err: unknown) {
      setMarketBatchMessage({ type: 'error', text: toErrorMessage(err, '批量更新失败') });
    }
  };

  const handleMarketBatchSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload = buildMarketBatchUpdatePayload(selectedMarketIds, marketBatchForm);
    await applyMarketBatchUpdate(payload);
  };

  const handleMarketBatchDelete = async () => {
    if (selectedMarketIds.length === 0) {
      setMarketBatchMessage({ type: 'error', text: '请先选择至少一条商品' });
      return;
    }
    if (!window.confirm(`确定删除选中的 ${selectedMarketIds.length} 条商品？该操作不可恢复。`)) {
      return;
    }
    setMarketBatchDeleting(true);
    setMarketBatchMessage(null);
    try {
      const resp = await fetchBackend('/admin/market/batch-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ itemIds: selectedMarketIds }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '批量删除失败');
      }
      const deleted = json.data?.deleted ?? 0;
      const failedIds: number[] = Array.isArray(json.data?.failedIds) ? json.data.failedIds : [];
      let text = `已删除 ${deleted} 条商品。`;
      if (failedIds.length) {
        text += ` ${failedIds.length} 条删除失败：${failedIds.join(', ')}`;
      }
      setMarketBatchMessage({
        type: failedIds.length ? 'error' : 'success',
        text,
      });
      setSelectedMarketIds(failedIds);
      await Promise.resolve(loadMarketItems(currentMarketPage));
    } catch (err: unknown) {
      setMarketBatchMessage({ type: 'error', text: toErrorMessage(err, '批量删除失败') });
    } finally {
      setMarketBatchDeleting(false);
    }
  };

  return {
    selectedMaterialIds,
    setSelectedMaterialIds,
    selectedMarketIds,
    setSelectedMarketIds,
    batchForm,
    batchMajorSelections,
    batchMessage,
    setBatchMessage,
    batchDeleting,
    batchRestoring,
    marketBatchForm,
    marketBatchMessage,
    setMarketBatchMessage,
    marketBatchDeleting,
    toggleMaterialSelection,
    selectAllMaterials,
    clearMaterialSelection,
    toggleMarketSelection,
    selectAllMarketItems,
    clearMarketSelection,
    handleBatchInputChange,
    handleBatchMajorToggle,
    handleMarketBatchInputChange,
    handleBatchSubmit,
    handleBatchDelete,
    handleBatchRestore,
    applyMarketBatchUpdate,
    handleMarketBatchSubmit,
    handleMarketBatchDelete,
  };
};
