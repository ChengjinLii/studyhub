import { Dispatch, SetStateAction, useEffect, useState } from 'react';
import { CourseCategoryValue, defaultCollege, GRADE_STAGE_OPTIONS, SUPPORTED_SCHOOL, normalizeCourseCategory } from '../constants/metadata';
import { MaterialDetail } from '../types/material';
import { ColumnTopicKey, resolveExperienceTopicFromTags } from './column';
import { toErrorMessage } from './errors';
import { parseMajorList } from './major';
import { fetchMaterialDetail } from './api';

type StatusSetter = Dispatch<SetStateAction<{ type: 'success' | 'error'; message: string } | null>>;
type StringSetter = Dispatch<SetStateAction<string>>;
type BooleanSetter = Dispatch<SetStateAction<boolean>>;
type FileListSetter = Dispatch<SetStateAction<File[]>>;

interface UseUploadExistingMaterialOptions {
  isEditing: boolean;
  editingId: string | null;
  token: string | null;
  setTitle: StringSetter;
  setDescription: StringSetter;
  setPrice: StringSetter;
  setSchool: StringSetter;
  setCollege: StringSetter;
  setSelectedMajors: Dispatch<SetStateAction<string[]>>;
  setCourseCategory: Dispatch<SetStateAction<CourseCategoryValue>>;
  setGradeValue: StringSetter;
  setSelectedTags: Dispatch<SetStateAction<string[]>>;
  setUploadMode: Dispatch<SetStateAction<'material' | 'experience'>>;
  setExperienceTopic: Dispatch<SetStateAction<ColumnTopicKey>>;
  setExperienceCustomTag: StringSetter;
  setZipPlaceholder: StringSetter;
  setHasExistingFile: BooleanSetter;
  setDeliveryMethod: Dispatch<SetStateAction<'FILE' | 'NETDISK'>>;
  setNetdiskUrl: StringSetter;
  setNetdiskPassword: StringSetter;
  setNetdiskExpiredAt: StringSetter;
  setNetdiskReminderAt: StringSetter;
  setCopyrightOwner: StringSetter;
  setPreviewWatermarkEnabled: BooleanSetter;
  setPreviewSource: Dispatch<SetStateAction<'AUTO' | 'MANUAL'>>;
  setManualPreviewFiles: FileListSetter;
  setManualPreviewNotice: Dispatch<SetStateAction<string | null>>;
  setCustomPreviewText: StringSetter;
  setExistingCustomPreviewImages: Dispatch<SetStateAction<string[]>>;
  setCustomPreviewFiles: FileListSetter;
  setCustomPreviewNotice: Dispatch<SetStateAction<string | null>>;
  setCustomPreviewClear: BooleanSetter;
  setStatus: StatusSetter;
}

const EXPERIENCE_SYSTEM_TAGS = new Set([
  '经验分享',
  '保研面经',
  '求职面经',
  '考研攻略',
  '留学指南',
  '考研心得',
  '留学心得',
]);

export function useUploadExistingMaterial({
  isEditing,
  editingId,
  token,
  setTitle,
  setDescription,
  setPrice,
  setSchool,
  setCollege,
  setSelectedMajors,
  setCourseCategory,
  setGradeValue,
  setSelectedTags,
  setUploadMode,
  setExperienceTopic,
  setExperienceCustomTag,
  setZipPlaceholder,
  setHasExistingFile,
  setDeliveryMethod,
  setNetdiskUrl,
  setNetdiskPassword,
  setNetdiskExpiredAt,
  setNetdiskReminderAt,
  setCopyrightOwner,
  setPreviewWatermarkEnabled,
  setPreviewSource,
  setManualPreviewFiles,
  setManualPreviewNotice,
  setCustomPreviewText,
  setExistingCustomPreviewImages,
  setCustomPreviewFiles,
  setCustomPreviewNotice,
  setCustomPreviewClear,
  setStatus,
}: UseUploadExistingMaterialOptions) {
  const [loadingExisting, setLoadingExisting] = useState(false);

  useEffect(() => {
    const loadMaterial = async () => {
      if (!isEditing || !editingId) return;
      setLoadingExisting(true);
      try {
        const detail: MaterialDetail = await fetchMaterialDetail(editingId, token || undefined);
        setTitle(detail.title || '');
        setDescription(detail.description || '');
        const detailPrice = detail.price != null ? Math.round(detail.price) : 0;
        setPrice(detailPrice > 0 ? String(detailPrice) : '0');
        setSchool(detail.school === SUPPORTED_SCHOOL ? detail.school : SUPPORTED_SCHOOL);
        const normalizedCategory = normalizeCourseCategory(detail.courseCategory, detail.generalEducation);
        setCourseCategory(normalizedCategory);
        const lockDepartment = normalizedCategory !== 'MAJOR';
        setCollege(lockDepartment ? '' : detail.college || defaultCollege);
        setSelectedMajors(lockDepartment ? [] : parseMajorList(detail.major));
        const resolvedGradeStage =
          detail.gradeValue && GRADE_STAGE_OPTIONS.includes(detail.gradeValue as (typeof GRADE_STAGE_OPTIONS)[number])
            ? detail.gradeValue
            : GRADE_STAGE_OPTIONS[0];
        setGradeValue(resolvedGradeStage);
        const resolvedTags = detail.tags || [];
        setSelectedTags(resolvedTags.slice(0, 3));
        setUploadMode(resolvedTags.includes('经验分享') ? 'experience' : 'material');
        const resolvedTopic = resolveExperienceTopicFromTags(resolvedTags);
        setExperienceTopic(resolvedTopic);
        if (resolvedTags.includes('经验分享')) {
          const extraCustomTag = resolvedTags.find((tag) => tag && !EXPERIENCE_SYSTEM_TAGS.has(tag));
          setExperienceCustomTag(extraCustomTag || '');
          if (extraCustomTag && (resolvedTopic === 'experience' || resolvedTopic === 'leetcode' || resolvedTopic === 'llm')) {
            setExperienceTopic('leetcode');
          }
        } else {
          setExperienceCustomTag('');
        }
        setZipPlaceholder(detail.originalFilename || '当前资料文件');
        setHasExistingFile(Boolean(detail.hasFile));
        setDeliveryMethod(detail.hasFile ? 'FILE' : detail.hasNetdisk ? 'NETDISK' : 'FILE');
        setNetdiskUrl(detail.netdiskUrl || '');
        setNetdiskPassword(detail.netdiskPassword || '');
        setNetdiskExpiredAt(detail.netdiskExpiredAt || '');
        setNetdiskReminderAt(detail.netdiskReminderAt || '');
        setCopyrightOwner(detail.copyrightOwner || '');
        setPreviewWatermarkEnabled(detail.previewWatermarkEnabled ?? true);
        setPreviewSource(detail.previewSource === 'MANUAL' ? 'MANUAL' : 'AUTO');
        setManualPreviewFiles([]);
        setManualPreviewNotice(null);
        setCustomPreviewText(detail.customPreviewText || '');
        setExistingCustomPreviewImages(detail.customPreviewImages || []);
        setCustomPreviewFiles([]);
        setCustomPreviewNotice(null);
        setCustomPreviewClear(false);
      } catch (err: unknown) {
        setStatus({ type: 'error', message: toErrorMessage(err, '加载资料信息失败') });
      } finally {
        setLoadingExisting(false);
      }
    };
    void loadMaterial();
  }, [
    editingId,
    isEditing,
    setCollege,
    setCopyrightOwner,
    setCourseCategory,
    setCustomPreviewClear,
    setCustomPreviewFiles,
    setCustomPreviewNotice,
    setCustomPreviewText,
    setDeliveryMethod,
    setDescription,
    setExistingCustomPreviewImages,
    setExperienceCustomTag,
    setExperienceTopic,
    setGradeValue,
    setHasExistingFile,
    setManualPreviewFiles,
    setManualPreviewNotice,
    setNetdiskExpiredAt,
    setNetdiskPassword,
    setNetdiskReminderAt,
    setNetdiskUrl,
    setPreviewSource,
    setPreviewWatermarkEnabled,
    setPrice,
    setSchool,
    setSelectedMajors,
    setSelectedTags,
    setStatus,
    setTitle,
    setUploadMode,
    setZipPlaceholder,
    token,
  ]);

  return { loadingExisting };
}
