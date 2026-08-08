import { UploadItem } from '../types/profile';

export type UploadTimeOrder = 'newest' | 'oldest';

const timestampOf = (value: string) => {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
};

export const sortUploadsByTime = (uploads: UploadItem[], order: UploadTimeOrder) =>
  [...uploads].sort((left, right) => {
    const leftTimestamp = timestampOf(left.createdAt);
    const rightTimestamp = timestampOf(right.createdAt);
    if (leftTimestamp === null && rightTimestamp !== null) return 1;
    if (leftTimestamp !== null && rightTimestamp === null) return -1;
    if (leftTimestamp !== null && rightTimestamp !== null && leftTimestamp !== rightTimestamp) {
      return order === 'newest' ? rightTimestamp - leftTimestamp : leftTimestamp - rightTimestamp;
    }
    return order === 'newest' ? right.materialId - left.materialId : left.materialId - right.materialId;
  });
