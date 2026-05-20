export type BatchTagsMode = 'replace' | 'append';

export interface MaterialBatchFormState {
  college: string;
  major: string;
  gradeValue: string;
  courseCategory: string;
  tags: string;
  tagsMode: BatchTagsMode;
}

export interface MarketBatchFormState {
  status: string;
  category: string;
  school: string;
  contactType: string;
  contactValue: string;
}

export interface MaterialBatchUpdatePayload {
  materialIds: number[];
  college?: string;
  major?: string;
  gradeValue?: string;
  courseCategory?: string;
  tags?: string;
  tagsMode?: BatchTagsMode;
}

export interface MarketBatchUpdatePayload {
  itemIds: number[];
  status?: string;
  category?: string;
  school?: string;
  contactType?: string;
  contactValue?: string;
}

export const buildMaterialBatchUpdatePayload = (
  selectedMaterialIds: number[],
  batchForm: MaterialBatchFormState
): MaterialBatchUpdatePayload => {
  const payload: MaterialBatchUpdatePayload = { materialIds: selectedMaterialIds };
  if (batchForm.college) payload.college = batchForm.college;
  if (batchForm.major) payload.major = batchForm.major;
  if (batchForm.gradeValue) payload.gradeValue = batchForm.gradeValue;
  if (batchForm.courseCategory) payload.courseCategory = batchForm.courseCategory;
  if (batchForm.tags) {
    payload.tags = batchForm.tags;
    payload.tagsMode = batchForm.tagsMode || 'replace';
  }
  return payload;
};

export const buildMarketBatchUpdatePayload = (
  selectedMarketIds: number[],
  marketBatchForm: MarketBatchFormState
): MarketBatchUpdatePayload => {
  const payload: MarketBatchUpdatePayload = { itemIds: selectedMarketIds };
  if (marketBatchForm.status) payload.status = marketBatchForm.status;
  if (marketBatchForm.category) payload.category = marketBatchForm.category;
  if (marketBatchForm.school) payload.school = marketBatchForm.school.trim();
  if (marketBatchForm.contactType) payload.contactType = marketBatchForm.contactType;
  if (marketBatchForm.contactValue) payload.contactValue = marketBatchForm.contactValue.trim();
  return payload;
};
