import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import AppImage from '../components/AppImage';
import NavBar from '../components/NavBar';
import UploadBasicSection from '../components/upload/UploadBasicSection';
import UploadChoiceCard from '../components/upload/UploadChoiceCard';
import UploadConfirmSection from '../components/upload/UploadConfirmSection';
import UploadHero from '../components/upload/UploadHero';
import UploadMaterialFileField from '../components/upload/UploadMaterialFileField';
import UploadMetaSection from '../components/upload/UploadMetaSection';
import UploadPolicyModal from '../components/upload/UploadPolicyModal';
import UploadProgressSidebar from '../components/upload/UploadProgressSidebar';
import SectionLabel from '../components/upload/UploadSectionLabel';
import { readSession } from '../lib/auth';
import { SessionUser } from '../types/user';
import { UserAccountProfile } from '../types/userProfile';
import {
  SUPPORTED_SCHOOL,
  defaultCollege,
  CourseCategorySelection,
  CourseCategoryValue,
  GRADE_STAGE_OPTIONS,
  getMajorOptionsForCollege,
} from '../constants/metadata';
import { fetchAccountProfile } from '../lib/api';
import { getRequestOrigin } from '../lib/apiBase';
import { ColumnTopicKey, getColumnTopicExtraTag, getColumnTopicTitle, isCommunityColumnTopic, normalizeColumnTopic } from '../lib/column';
import { resolveApiBase } from '../lib/apiBase';
import { toErrorMessage } from '../lib/errors';
import { parseMajorList } from '../lib/major';
import { materialPath } from '../lib/slug';
import { buildZipName, resolveZipFileName, zipFiles, zipMarkdownContent } from '../lib/uploadAssets';
import { buildUploadPayload } from '../lib/uploadPayload';
import { describeUploadFile, requestMaterialUploadAuthorization } from '../lib/uploadAuthorization';
import { isUploadResultUncertain, sendUploadFormData } from '../lib/uploadSubmit';
import {
  buildUploadSubmissionFingerprint,
  clearUploadSubmission,
  resolveUploadSubmissionId,
  UploadSubmissionStage,
} from '../lib/uploadSubmission';
import { formatPriceSummary, normalizePriceInput, sanitizePriceInput, validateUploadSubmitInput } from '../lib/uploadValidation';
import { useSectionNavigation } from '../lib/useSectionNavigation';
import { useUploadExistingMaterial } from '../lib/useUploadExistingMaterial';
import { useUploadImageSelection } from '../lib/useUploadImageSelection';
import { resolveUploadSectionCompletion } from '../lib/uploadSectionCompletion';

const presetTags = [
  '日常学习笔记',
  '期末速成',
  '期末真题',
  '期末真题标答',
  '期末答案（自制解析）',
  '期中速成',
  '期中真题',
  '期中真题标答',
  '期中答案（自制解析）',
  '一页纸',
  '开卷资料',
  '教材',
  '教材答案',
];

const currentYear = new Date().getFullYear();
const yearSuggestions = Array.from({ length: 6 }, (_, index) => currentYear - index)
  .flatMap((year) => [year.toString(), `${year}-${year + 1}`])
  .filter((value, index, array) => array.indexOf(value) === index);

const MAX_FILE_BYTES = 50 * 1024 * 1024;
const MAX_TAGS = 3;
const MAX_TITLE_LENGTH = 80;
const MAX_DESC_LENGTH = 300;
const MAX_EXPERIENCE_LENGTH = 3000;
const MAX_COPYRIGHT_LENGTH = 8;

const PREVIEW_SOURCE_AUTO = 'AUTO';
const PREVIEW_SOURCE_MANUAL = 'MANUAL';
const MAX_PREVIEW_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_PREVIEW_IMAGES = 10;
const MAX_CUSTOM_PREVIEW_TEXT = 800;
const MAX_CUSTOM_PREVIEW_IMAGES = 5;
const MIN_MANUAL_PREVIEW_IMAGES = 1;
const MIN_REQUEST_PREVIEW_IMAGES = 2;
const QUICK_UPLOAD_OPTIONS: string[] = [];
const UPLOAD_NAV_ITEMS = [
  { id: 'upload-basic', label: '基础信息' },
  { id: 'upload-meta', label: '课程与标签' },
  { id: 'upload-delivery', label: '交付与预览' },
  { id: 'upload-confirm', label: '发布确认' },
];

interface UploadPageProps {
  user: SessionUser | null;
  token: string | null;
  account: UserAccountProfile | null;
}

const resolveMaterialProfilePrefill = (account: UserAccountProfile | null) => {
  const accountCollege = account?.college?.trim();
  const accountMajor = account?.major?.trim();
  const accountGrades = Array.isArray(account?.gradeStages) ? account.gradeStages.filter(Boolean) : [];
  const matchedGrade = accountGrades.find((stage) => GRADE_STAGE_OPTIONS.includes(stage as (typeof GRADE_STAGE_OPTIONS)[number])) || '';
  const resolvedMajors = accountMajor ? parseMajorList(accountMajor) : [];
  return {
    school: SUPPORTED_SCHOOL,
    college: accountCollege || defaultCollege,
    majors: resolvedMajors,
    gradeValue: matchedGrade || GRADE_STAGE_OPTIONS[0],
  };
};

export default function UploadPage({ user, token, account }: UploadPageProps) {
  const router = useRouter();
  const editingId = typeof router.query.materialId === 'string' ? router.query.materialId : null;
  const isEditing = Boolean(editingId);
  const materialProfilePrefill = resolveMaterialProfilePrefill(account);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [uploadMode, setUploadMode] = useState<'material' | 'experience'>('material');
  const [experienceTopic, setExperienceTopic] = useState<ColumnTopicKey>('experience');
  const [experienceCustomTag, setExperienceCustomTag] = useState('');
  const [price, setPrice] = useState('0');
  const [school, setSchool] = useState(materialProfilePrefill.school);
  const [college, setCollege] = useState<string>(materialProfilePrefill.college);
  const [selectedMajors, setSelectedMajors] = useState<string[]>(materialProfilePrefill.majors);
  const [policyModalOpen, setPolicyModalOpen] = useState(false);
  const gradeStageOptions = GRADE_STAGE_OPTIONS;
  const [gradeValue, setGradeValue] = useState<string>(materialProfilePrefill.gradeValue);
  const [courseCategory, setCourseCategory] = useState<CourseCategorySelection>('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [customTags, setCustomTags] = useState('');
  const [yearTag, setYearTag] = useState('');
  const [zipFile, setZipFile] = useState<File | null>(null);
  const zipInputRef = useRef<HTMLInputElement | null>(null);
  const [zipSourceCount, setZipSourceCount] = useState(0);
  const [zipPreparing, setZipPreparing] = useState(false);
  const zipTaskRef = useRef(0);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [deliveryMethod, setDeliveryMethod] = useState<'FILE' | 'NETDISK'>('FILE');
  const [previewWatermarkEnabled, setPreviewWatermarkEnabled] = useState(true);
  const [previewSource, setPreviewSource] = useState<'AUTO' | 'MANUAL'>(PREVIEW_SOURCE_AUTO);
  const isExperience = uploadMode === 'experience';
  const customPreviewLabel = isExperience ? '经验配图' : '自定义预览图';
  const manualPreviewSelection = useUploadImageSelection({
    label: '预览图',
    maxFiles: MAX_PREVIEW_IMAGES,
    maxFileBytes: MAX_PREVIEW_IMAGE_BYTES,
  });
  const [customPreviewText, setCustomPreviewText] = useState('');
  const customPreviewSelection = useUploadImageSelection({
    label: customPreviewLabel,
    maxFiles: MAX_CUSTOM_PREVIEW_IMAGES,
    maxFileBytes: MAX_PREVIEW_IMAGE_BYTES,
  });
  const [customPreviewClear, setCustomPreviewClear] = useState(false);
  const [existingCustomPreviewImages, setExistingCustomPreviewImages] = useState<string[]>([]);
  const [requestPreviewRequirement, setRequestPreviewRequirement] = useState('');
  const [hasExistingFile, setHasExistingFile] = useState(false);
  const [netdiskUrl, setNetdiskUrl] = useState('');
  const [netdiskPassword, setNetdiskPassword] = useState('');
  const [netdiskExpiredAt, setNetdiskExpiredAt] = useState('');
  const [netdiskReminderAt, setNetdiskReminderAt] = useState('');
  const [copyrightOwner, setCopyrightOwner] = useState('');
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [submissionStage, setSubmissionStage] = useState<UploadSubmissionStage>('idle');
  const [successPath, setSuccessPath] = useState<string | null>(null);
  const [agreementAccepted, setAgreementAccepted] = useState(false);
  const [zipPlaceholder, setZipPlaceholder] = useState('未选择任何文件');
  const [quickPanelOpen, setQuickPanelOpen] = useState(false);
  const [quickSelectedOption, setQuickSelectedOption] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<number | null>(null);
  const [requestPrefilled, setRequestPrefilled] = useState(false);
  const uploadRequestRef = useRef<XMLHttpRequest | null>(null);
  const submissionInFlightRef = useRef(false);
  const allowSubmissionNavigationRef = useRef(false);
  const submitting = submissionStage !== 'idle';
  const apiBase = useMemo(() => resolveApiBase(typeof window !== 'undefined' ? window.location.origin : undefined), []);
  const isExperienceCustomTopic = experienceTopic === 'leetcode';
  const experienceTopicTitle = getColumnTopicTitle(experienceTopic);
  const experienceTopicExtraTagRaw = getColumnTopicExtraTag(experienceTopic);
  const experienceTopicExtraTag =
    experienceTopic === 'experience'
      ? null
      : experienceTopic === 'grad-school' ||
          experienceTopic === 'career' ||
          experienceTopic === 'postgrad-exam' ||
          experienceTopic === 'overseas'
        ? experienceTopicExtraTagRaw
        : null;
  const resolvedExperienceExtraTag =
    experienceTopic === 'leetcode' && experienceCustomTag.trim() ? experienceCustomTag.trim() : experienceTopicExtraTag;
  const isRequestResponse = !isEditing && requestId != null;
  const isQuickMode = !isEditing && uploadMode === 'material' && quickPanelOpen && !isRequestResponse;
  const uploadNavItems = useMemo(() => {
    if (isExperience) {
      return UPLOAD_NAV_ITEMS.filter((item) => item.id !== 'upload-delivery');
    }
    return UPLOAD_NAV_ITEMS;
  }, [isExperience]);
  const { activeSection, jumpToSection } = useSectionNavigation(uploadNavItems, {
    rootMargin: '-24% 0px -58% 0px',
    threshold: [0.12, 0.38, 0.72],
  });
  const descriptionLimit = isExperience ? MAX_EXPERIENCE_LENGTH : MAX_DESC_LENGTH;
  const customPreviewTitle = isExperience ? '经验配图' : '自定义预览';
  const customPreviewHint = isExperience
    ? '可选：最多上传 5 张配图，单张 ≤ 5MB，无水印。'
    : '可选：图文结合展示，文字最多 800 字，图片最多 5 张。';
  const {
    files: manualPreviewFiles,
    notice: manualPreviewNotice,
    setFiles: setManualPreviewFiles,
    setNotice: setManualPreviewNotice,
    inputRef: manualPreviewInputRef,
    handleSelection: handleManualPreviewSelection,
    removeFile: removeManualPreviewFile,
    clearFiles: clearManualPreviewFiles,
  } = manualPreviewSelection;
  const {
    files: customPreviewFiles,
    notice: customPreviewNotice,
    setFiles: setCustomPreviewFiles,
    setNotice: setCustomPreviewNotice,
    inputRef: customPreviewInputRef,
    handleSelection: handleCustomPreviewFilesSelection,
    removeFile: removeCustomPreviewFile,
    clearFiles: clearCustomPreviewFiles,
  } = customPreviewSelection;
  const priceSummary = useMemo(() => formatPriceSummary(price), [price]);
  const hasPayoutQr = Boolean(account?.payoutQrUrl);
  const experienceHeading = isExperienceCustomTopic ? '经验分享' : experienceTopic === 'experience' ? '经验分享' : experienceTopicTitle;
  const quickProfile = useMemo(() => {
    const accountSchool = account?.school?.trim();
    const accountCollege = account?.college?.trim();
    const accountMajor = account?.major?.trim();
    const accountGrades = Array.isArray(account?.gradeStages) ? account?.gradeStages.filter(Boolean) : [];
    const matchedGrade = accountGrades.find((stage) => GRADE_STAGE_OPTIONS.includes(stage as (typeof GRADE_STAGE_OPTIONS)[number])) || '';
    const resolvedSchool = accountSchool || SUPPORTED_SCHOOL;
    const resolvedCollege = accountCollege || defaultCollege;
    const resolvedMajors = accountMajor ? parseMajorList(accountMajor) : [];
    const resolvedGradeValue = matchedGrade || gradeStageOptions[0];
    return {
      school: resolvedSchool,
      college: resolvedCollege,
      majors: resolvedMajors,
      majorDisplay: accountMajor || '未填写',
      gradeValue: resolvedGradeValue,
    };
  }, [account, gradeStageOptions]);
  const sectionCompletion = resolveUploadSectionCompletion({
    isExperience,
    isQuickMode,
    isExperienceCustomTopic,
    title,
    description,
    experienceCustomTag,
    price,
    school: isQuickMode ? quickProfile.school : school,
    college: isQuickMode ? quickProfile.college : college,
    gradeValue: isQuickMode ? quickProfile.gradeValue : gradeValue,
    courseCategory,
    deliveryMethod,
    hasSelectedFile: Boolean(zipFile),
    hasExistingFile,
    zipPreparing,
    netdiskUrl,
    previewSource: isRequestResponse ? PREVIEW_SOURCE_MANUAL : previewSource,
    isRequestResponse,
    isEditing,
    manualPreviewCount: manualPreviewFiles.length,
    minManualPreviewImages: MIN_MANUAL_PREVIEW_IMAGES,
    minRequestPreviewImages: MIN_REQUEST_PREVIEW_IMAGES,
    agreementAccepted,
  });
  const { loadingExisting } = useUploadExistingMaterial({
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
  });

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!submissionInFlightRef.current || allowSubmissionNavigationRef.current) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, []);

  useEffect(() => {
    if (!courseCategory) return;
    if (courseCategory === 'MAJOR') {
      setCollege((prev) => (prev ? prev : defaultCollege));
      setSelectedMajors((prev) => (prev.length > 0 ? prev : []));
    } else {
      setCollege('');
      setSelectedMajors([]);
    }
  }, [courseCategory]);

  useEffect(() => {
    if (previewSource === PREVIEW_SOURCE_AUTO) {
      setManualPreviewNotice(null);
      setManualPreviewFiles([]);
    }
  }, [previewSource, setManualPreviewFiles, setManualPreviewNotice]);

  useEffect(() => {
    if (isEditing || requestPrefilled) return;
    const rawRequestId = typeof router.query.requestId === 'string' ? router.query.requestId : '';
    const parsedRequestId = rawRequestId ? Number(rawRequestId) : NaN;
    if (!Number.isNaN(parsedRequestId)) {
      setRequestId(parsedRequestId);
    }
    const previewRule = typeof router.query.previewRequirement === 'string' ? router.query.previewRequirement : '';
    setRequestPreviewRequirement(previewRule || '');
    const course = typeof router.query.course === 'string' ? router.query.course : '';
    const keyword = typeof router.query.keyword === 'string' ? router.query.keyword : '';
    const titleSeed = course || keyword;
    if (titleSeed && !title) {
      setTitle(titleSeed);
    }
    const budgetValue = typeof router.query.budget === 'string' ? Number(router.query.budget) : NaN;
    if (!Number.isNaN(budgetValue) && budgetValue >= 0) {
      const normalizedBudget = Math.max(0, Math.round(budgetValue));
      setPrice(String(normalizedBudget));
    }
    if (!Number.isNaN(parsedRequestId)) {
      setPreviewSource(PREVIEW_SOURCE_MANUAL);
    }
    setRequestPrefilled(true);
  }, [router.query, isEditing, requestPrefilled, title]);

  useEffect(() => {
    if (isEditing) return;
    const rawTopic = typeof router.query.topic === 'string' ? router.query.topic : null;
    if (!rawTopic) return;
    const nextTopic = normalizeColumnTopic(rawTopic);
    setExperienceTopic(isCommunityColumnTopic(nextTopic) ? nextTopic : 'experience');
    setExperienceCustomTag('');
    setUploadMode('experience');
    setQuickPanelOpen(false);
    setQuickSelectedOption(null);
    setDeliveryMethod('FILE');
    setNetdiskUrl('');
    setNetdiskPassword('');
    setNetdiskExpiredAt('');
    setNetdiskReminderAt('');
    setPrice('0');
    setCopyrightOwner('');
    setPreviewSource(PREVIEW_SOURCE_AUTO);
    clearManualPreviewFiles();
    setStatus(null);
  }, [clearManualPreviewFiles, isEditing, router.query.topic]);

  useEffect(() => {
    if (isEditing || !isExperience) return;
    setCollege('');
    setSelectedMajors([]);
    setSelectedTags([]);
    setCustomTags('');
    setYearTag('');
  }, [isEditing, isExperience]);

  const tagComputation = useMemo(() => {
    if (isExperience) {
      return {
        list: ['经验分享', ...(resolvedExperienceExtraTag ? [resolvedExperienceExtraTag] : [])],
        trimmedCustom: false,
      };
    }
    const trimmedYear = yearTag.trim();
    const baseSet = new Set<string>(selectedTags.filter((tag) => tag !== '经验分享'));
    if (trimmedYear) {
      if (trimmedYear !== '经验分享') {
        baseSet.add(trimmedYear);
      }
    }
    const customEntries = Array.from(
      new Set(
        customTags
          .split(/[,，\s]+/)
          .map((tag) => tag.trim())
          .filter((tag) => tag && tag !== '经验分享')
      )
    );
    const combined: string[] = [];
    Array.from(baseSet).forEach((tag) => {
      if (combined.length < MAX_TAGS) combined.push(tag);
    });
    let trimmedCustom = false;
    for (const tag of customEntries) {
      if (combined.length >= MAX_TAGS) {
        trimmedCustom = true;
        break;
      }
      if (!combined.includes(tag)) {
        combined.push(tag);
      }
    }
    return {
      list: combined.slice(0, MAX_TAGS),
      trimmedCustom,
    };
  }, [selectedTags, customTags, yearTag, isExperience, resolvedExperienceExtraTag]);
  const tagList = tagComputation.list;
  const trimmedCustom = tagComputation.trimmedCustom;

  const handleMajorToggle = (name: string, checked: boolean) => {
    setSelectedMajors((prev) => {
      if (checked) {
        if (prev.includes(name)) return prev;
        return [...prev, name];
      }
      return prev.filter((item) => item !== name);
    });
  };

  const clearZipFile = () => {
    if (submissionInFlightRef.current) return;
    if (uploadRequestRef.current) {
      uploadRequestRef.current.abort();
      uploadRequestRef.current = null;
    }
    zipTaskRef.current += 1;
    setZipFile(null);
    setZipSourceCount(0);
    setZipPreparing(false);
    setUploadProgress(null);
    if (zipInputRef.current) {
      zipInputRef.current.value = '';
    }
  };

  const handleCustomPreviewSelection = (files: FileList | null) => {
    if (!files) return;
    setCustomPreviewClear(false);
    setExistingCustomPreviewImages([]);
    handleCustomPreviewFilesSelection(files);
  };

  const clearCustomPreviewAll = () => {
    setCustomPreviewText('');
    setCustomPreviewClear(true);
    setCustomPreviewNotice(null);
    setExistingCustomPreviewImages([]);
    clearCustomPreviewFiles();
  };

  const handleZipSelection = async (fileList: FileList | null) => {
    if (submissionInFlightRef.current) return;
    const files = fileList ? Array.from(fileList) : [];
    const taskId = ++zipTaskRef.current;
    if (files.length === 0) {
      clearZipFile();
      return;
    }
    setZipPreparing(false);
    setZipFile(null);
    setUploadProgress(null);
    const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
    if (totalBytes > MAX_FILE_BYTES) {
      setStatus({ type: 'error', message: '文件总大小需小于 50MB，请改用网盘链接。' });
      clearZipFile();
      return;
    }
    setZipSourceCount(files.length);
    if (isQuickMode && !title.trim()) {
      setTitle(deriveAutoTitle(files[0].name));
    }
    if (files.length === 1) {
      setZipFile(files[0]);
      return;
    }
    setZipPreparing(true);
    try {
      const zipName = buildZipName(title, deriveAutoTitle(files[0].name), MAX_TITLE_LENGTH);
      const zipped = await zipFiles(files, zipName, MAX_FILE_BYTES);
      if (zipTaskRef.current !== taskId) return;
      setZipFile(zipped);
    } catch (error: unknown) {
      if (zipTaskRef.current !== taskId) return;
      setStatus({ type: 'error', message: toErrorMessage(error, '文件打包失败，请重试。') });
      clearZipFile();
    } finally {
      if (zipTaskRef.current === taskId) {
        setZipPreparing(false);
      }
    }
  };

  const deriveAutoTitle = (name: string) => {
    const withoutExt = name.replace(/\.[^/.]+$/, '');
    return withoutExt.slice(0, MAX_TITLE_LENGTH);
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (submissionInFlightRef.current) return;
    setStatus(null);
    const fallbackGradeValue = gradeStageOptions[0];
    const effectiveTitle = (title.trim() || (isQuickMode && zipFile ? deriveAutoTitle(zipFile.name) : '')).slice(0, MAX_TITLE_LENGTH);
    const effectiveGradeValue = isQuickMode ? quickProfile.gradeValue || fallbackGradeValue : gradeValue;
    const effectiveCourseCategory: CourseCategorySelection = isExperience ? 'GENERAL' : courseCategory;
    const effectiveCollege = effectiveCourseCategory === 'MAJOR' ? (isQuickMode ? quickProfile.college : college) : '';
    const effectiveMajors = effectiveCourseCategory === 'MAJOR' ? (isQuickMode ? quickProfile.majors : selectedMajors) : [];
    const effectiveTagList = isQuickMode ? [] : tagList;
    const trimmedNetdiskUrl = netdiskUrl.trim();
    const resolvedDelivery = isExperience ? 'FILE' : deliveryMethod === 'NETDISK' ? 'NETDISK' : 'FILE';
    const effectivePreviewSource = isExperience
      ? PREVIEW_SOURCE_AUTO
      : isRequestResponse
        ? PREVIEW_SOURCE_MANUAL
        : isQuickMode
          ? PREVIEW_SOURCE_AUTO
          : previewSource;
    const allowCustomPreview = isExperience;
    const validation = validateUploadSubmitInput({
      token,
      isExperience,
      description,
      isExperienceCustomTopic,
      experienceCustomTag,
      customTags,
      zipPreparing,
      resolvedDelivery,
      zipFile,
      hasExistingFile,
      trimmedNetdiskUrl,
      effectivePreviewSource,
      isRequestResponse,
      isEditing,
      manualPreviewFiles,
      customPreviewText: allowCustomPreview ? customPreviewText : '',
      isQuickMode,
      customPreviewFiles: allowCustomPreview ? customPreviewFiles : [],
      customPreviewLabel,
      effectiveTitle,
      descriptionLimit,
      copyrightOwner,
      price,
      courseCategory: effectiveCourseCategory,
      limits: {
        maxTitleLength: MAX_TITLE_LENGTH,
        maxDescLength: MAX_DESC_LENGTH,
        maxExperienceLength: MAX_EXPERIENCE_LENGTH,
        maxCopyrightLength: MAX_COPYRIGHT_LENGTH,
        maxPreviewImageBytes: MAX_PREVIEW_IMAGE_BYTES,
        maxCustomPreviewText: MAX_CUSTOM_PREVIEW_TEXT,
        maxCustomPreviewImages: MAX_CUSTOM_PREVIEW_IMAGES,
        minManualPreviewImages: MIN_MANUAL_PREVIEW_IMAGES,
        minRequestPreviewImages: MIN_REQUEST_PREVIEW_IMAGES,
      },
    });
    if (validation.error) {
      setStatus({ type: 'error', message: validation.error });
      return;
    }
    if (!effectiveCourseCategory) {
      setStatus({ type: 'error', message: '请选择课程类型。' });
      return;
    }
    const selectedCourseCategory: CourseCategoryValue = effectiveCourseCategory;
    const resolvedPriceValue = validation.priceValue;
    let completed = false;
    let uploadTransferred = false;
    let submissionId: string | null = null;
    try {
      submissionInFlightRef.current = true;
      allowSubmissionNavigationRef.current = false;
      setSuccessPath(null);
      setSubmissionStage('preparing');
      setUploadProgress(isExperience || zipFile ? 0 : null);
      const trimmedTitle = effectiveTitle;
      const trimmedDescription = description.trim();
      const trimmedCustomPreviewText = allowCustomPreview ? customPreviewText.trim() : '';
      const payload = buildUploadPayload({
        title: trimmedTitle,
        description: trimmedDescription,
        priceValue: resolvedPriceValue,
        school: isQuickMode ? quickProfile.school : SUPPORTED_SCHOOL,
        college: effectiveCollege,
        majors: effectiveMajors,
        gradeValue: effectiveGradeValue,
        courseCategory: selectedCourseCategory,
        tags: effectiveTagList,
        deliveryMethod: resolvedDelivery,
        netdiskUrl: trimmedNetdiskUrl,
        netdiskPassword,
        netdiskExpiredAt,
        netdiskReminderAt,
        previewWatermarkEnabled,
        previewSource: effectivePreviewSource,
        customPreviewText: trimmedCustomPreviewText,
        copyrightOwner,
        isExperience,
        isQuickMode,
        isEditing,
        requestId,
        customPreviewClear,
      });
      const formData = new FormData();
      let uploadFile = zipFile && zipSourceCount > 1 ? resolveZipFileName(zipFile, trimmedTitle, MAX_TITLE_LENGTH) : zipFile;
      if (isExperience) {
        setZipPreparing(true);
        try {
          uploadFile = await zipMarkdownContent(trimmedTitle, trimmedDescription, MAX_FILE_BYTES, MAX_TITLE_LENGTH);
        } finally {
          setZipPreparing(false);
        }
      }
      formData.append('payload', new Blob([JSON.stringify(payload)], { type: 'application/json' }));
      if (uploadFile) {
        formData.append('zip', uploadFile);
      }
      const submittedPreviews = !isExperience && !isQuickMode && effectivePreviewSource === PREVIEW_SOURCE_MANUAL ? manualPreviewFiles : [];
      const submittedCustomPreviews = allowCustomPreview ? customPreviewFiles : [];
      submittedPreviews.forEach((file) => formData.append('previews', file));
      submittedCustomPreviews.forEach((file) => formData.append('customPreviews', file));
      if (!isEditing) {
        const fingerprint = await buildUploadSubmissionFingerprint({
          payload,
          file: uploadFile
            ? {
                name: uploadFile.name,
                size: uploadFile.size,
                type: uploadFile.type,
                lastModified: isExperience || zipSourceCount > 1 ? null : uploadFile.lastModified,
              }
            : null,
          previews: manualPreviewFiles.map((file) => [file.name, file.size, file.lastModified]),
          customPreviews: customPreviewFiles.map((file) => [file.name, file.size, file.lastModified]),
        });
        submissionId = resolveUploadSubmissionId(fingerprint, window.sessionStorage);
        payload.submissionId = submissionId;
        formData.set('payload', new Blob([JSON.stringify(payload)], { type: 'application/json' }));
      }
      let uploadAuthorizationToken: string | null = null;
      if (!isEditing && submissionId) {
        const authorization = await requestMaterialUploadAuthorization(
          submissionId,
          [
            ...(uploadFile ? [describeUploadFile('MATERIAL', uploadFile)] : []),
            ...submittedPreviews.map((file) => describeUploadFile('PREVIEW', file)),
            ...submittedCustomPreviews.map((file) => describeUploadFile('CUSTOM_PREVIEW', file)),
          ],
          token
        );
        uploadAuthorizationToken = authorization.uploadToken;
      }
      const endpoint = isEditing ? `${apiBase}/materials/${editingId}` : `${apiBase}/materials`;
      const method = isEditing ? 'PUT' : 'POST';
      setSubmissionStage('uploading');
      const json = await sendUploadFormData(endpoint, method, formData, {
        token,
        uploadToken: uploadAuthorizationToken,
        onProgress: (value) => {
          setUploadProgress(value);
          if (value >= 100) {
            uploadTransferred = true;
            setSubmissionStage('processing');
          }
        },
        requestRef: uploadRequestRef,
      });
      if (isQuickMode && !title.trim()) {
        setTitle(trimmedTitle);
      }
      const destination = materialPath(json.data.id, json.data.title || trimmedTitle);
      if (submissionId) {
        clearUploadSubmission(window.sessionStorage, submissionId);
      }
      completed = true;
      submissionInFlightRef.current = false;
      allowSubmissionNavigationRef.current = true;
      setUploadProgress(100);
      setSuccessPath(destination);
      setSubmissionStage('redirecting');
      setStatus({ type: 'success', message: isEditing ? '更新成功。' : '投稿成功。' });
      window.setTimeout(() => window.location.replace(destination), 80);
    } catch (error: unknown) {
      const errorMessage = toErrorMessage(error, '投稿失败');
      const fallback =
        uploadTransferred && isUploadResultUncertain(error)
          ? `连接已中断，但服务器可能仍在保存资料。请不要新建投稿，稍后直接重新提交，系统会识别同一次投稿。（${errorMessage}）`
          : `${isEditing ? '更新' : '投稿'}未成功：${errorMessage}`;
      setStatus({ type: 'error', message: fallback });
    } finally {
      uploadRequestRef.current = null;
      if (!completed) {
        submissionInFlightRef.current = false;
        setSubmissionStage('idle');
        setUploadProgress(null);
      }
    }
  };

  const switchUploadMode = (nextMode: 'material' | 'experience') => {
    setUploadMode(nextMode);
    if (nextMode === 'experience') {
      setQuickPanelOpen(false);
      setQuickSelectedOption(null);
      setDeliveryMethod('FILE');
      setNetdiskUrl('');
      setNetdiskPassword('');
      setNetdiskExpiredAt('');
      setNetdiskReminderAt('');
      setPrice('0');
      setCopyrightOwner('');
      setPreviewSource(PREVIEW_SOURCE_AUTO);
      clearManualPreviewFiles();
    }
  };

  const toggleQuickPanel = () => {
    if (uploadMode === 'experience') {
      switchUploadMode('material');
    }
    setStatus(null);
    setQuickPanelOpen((prev) => {
      const next = !prev;
      if (!next) {
        setQuickSelectedOption(null);
      }
      return next;
    });
  };

  const handleQuickOptionSelect = (option: string) => {
    setQuickSelectedOption((prev) => (prev === option ? prev : option));
    setQuickPanelOpen(true);
    if (!title.trim()) {
      setTitle(option);
    }
  };

  const pageTitle = isEditing
    ? isExperience
      ? `编辑${experienceHeading}`
      : '编辑资料'
    : uploadMode === 'experience'
      ? experienceTopic === 'experience'
        ? '经验分享'
        : isExperienceCustomTopic
          ? '经验分享'
          : `${experienceHeading}投稿`
      : '资料投稿';

  const formContent = (
    <form
      id="upload-form"
      className={`upload-stacked-form${submitting ? ' is-submitting' : ''}`}
      onSubmit={handleSubmit}
      aria-busy={submitting}
    >
      <UploadBasicSection
        isExperience={isExperience}
        isQuickMode={isQuickMode}
        experienceHeading={experienceHeading}
        title={title}
        description={description}
        descriptionLimit={descriptionLimit}
        maxTitleLength={MAX_TITLE_LENGTH}
        price={price}
        priceSummary={priceSummary}
        hasPayoutQr={hasPayoutQr}
        customPreviewTitle={customPreviewTitle}
        customPreviewHint={customPreviewHint}
        customPreviewLabel={customPreviewLabel}
        customPreviewFiles={customPreviewFiles}
        customPreviewNotice={customPreviewNotice}
        existingCustomPreviewImages={existingCustomPreviewImages}
        maxCustomPreviewImages={MAX_CUSTOM_PREVIEW_IMAGES}
        customPreviewInputRef={customPreviewInputRef}
        onTitleChange={setTitle}
        onDescriptionChange={setDescription}
        onPriceChange={(value) => setPrice(sanitizePriceInput(value))}
        onPriceBlur={() => setPrice(normalizePriceInput(price))}
        onCustomPreviewSelection={handleCustomPreviewSelection}
        onClearCustomPreviewFiles={clearCustomPreviewFiles}
        onRemoveCustomPreviewFile={removeCustomPreviewFile}
        onClearCustomPreviewAll={clearCustomPreviewAll}
      />

      <UploadMetaSection
        isExperience={isExperience}
        isQuickMode={isQuickMode}
        isExperienceCustomTopic={isExperienceCustomTopic}
        experienceTopic={experienceTopic}
        experienceCustomTag={experienceCustomTag}
        quickProfile={quickProfile}
        school={school}
        college={college}
        gradeValue={gradeValue}
        gradeStageOptions={gradeStageOptions}
        selectedMajors={selectedMajors}
        courseCategory={courseCategory}
        selectedTags={selectedTags}
        customTags={customTags}
        yearTag={yearTag}
        yearSuggestions={yearSuggestions}
        presetTags={presetTags}
        tagList={tagList}
        maxTags={MAX_TAGS}
        trimmedCustom={trimmedCustom}
        onExperienceTopicChange={setExperienceTopic}
        onExperienceCustomTagChange={setExperienceCustomTag}
        onSchoolChange={setSchool}
        onCollegeChange={(value) => {
          setCollege(value);
          const availableMajors = getMajorOptionsForCollege(value);
          setSelectedMajors((current) => current.filter((name) => availableMajors.includes(name)));
        }}
        onGradeValueChange={setGradeValue}
        onMajorToggle={handleMajorToggle}
        onCourseCategoryChange={setCourseCategory}
        onSelectedTagsChange={setSelectedTags}
        onCustomTagsChange={setCustomTags}
        onYearTagChange={setYearTag}
      />

      {!isExperience && (
        <div className="upload-section-shell" id="upload-delivery">
          <div className="upload-section-heading">
            <div className="upload-section-heading__copy">
              <h2 className="upload-section-heading__title">交付与预览</h2>
            </div>
          </div>
          <section className="card upload-main-card upload-section-card">
            <div className="form-grid upload-section-grid">
              <div className="form-item full">
                <SectionLabel text="资料交付方式" selectionHint="请选择 1 项" />
                <div className="delivery-method-options" role="radiogroup" aria-label="资料交付方式">
                  <UploadChoiceCard
                    name="deliveryMethod"
                    value="FILE"
                    title="站内文件交付"
                    description="后续在下方选择文件，单次总大小不超过 50MB。"
                    selected={deliveryMethod === 'FILE'}
                    onSelect={() => setDeliveryMethod('FILE')}
                  />
                  <UploadChoiceCard
                    name="deliveryMethod"
                    value="NETDISK"
                    title="网盘链接交付"
                    description="适合超过 50MB 或需要外部维护的资料。"
                    selected={deliveryMethod === 'NETDISK'}
                    onSelect={() => setDeliveryMethod('NETDISK')}
                  />
                </div>
                <p className="help-text">
                  {isQuickMode
                    ? '一键投稿默认自动生成预览，仅保留文件交付与网盘链接两种方式。'
                    : '超过 50MB 或特殊格式的资料请改用网盘链接，确保链接长期有效。'}
                </p>
              </div>
              {!isQuickMode && (
                <div className="form-item full">
                  <SectionLabel text="预览图设置" selectionHint="请选择 1 项" />
                  {isRequestResponse ? (
                    <p className="help-text">
                      请上传符合求购者要求的预览图
                      {requestPreviewRequirement ? `：${requestPreviewRequirement}` : '。'}
                    </p>
                  ) : (
                    <>
                      <div className="upload-preview-source-options" role="radiogroup" aria-label="预览图设置">
                        <UploadChoiceCard
                          name="previewSource"
                          value={PREVIEW_SOURCE_AUTO}
                          title="自动生成（推荐）"
                          description="系统从资料文件生成预览，PDF 文件效果最佳。"
                          selected={previewSource === PREVIEW_SOURCE_AUTO}
                          onSelect={() => setPreviewSource(PREVIEW_SOURCE_AUTO)}
                        />
                        <UploadChoiceCard
                          name="previewSource"
                          value={PREVIEW_SOURCE_MANUAL}
                          title="手动上传"
                          description="自行选择展示内容，至少上传 1 张预览图。"
                          selected={previewSource === PREVIEW_SOURCE_MANUAL}
                          onSelect={() => setPreviewSource(PREVIEW_SOURCE_MANUAL)}
                        />
                      </div>
                      {previewSource === PREVIEW_SOURCE_AUTO && (
                        <p className="help-text">系统将自动生成预览图（PDF 最佳）。如需自定义可切换手动上传。</p>
                      )}
                    </>
                  )}
                  {(isRequestResponse || previewSource === PREVIEW_SOURCE_MANUAL) && (
                    <div className="form-item full">
                      <div
                        className="file-field drop-zone"
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={(e) => {
                          e.preventDefault();
                          handleManualPreviewSelection(e.dataTransfer.files);
                        }}
                      >
                        <span className="file-trigger">选择预览图</span>
                        <span className="file-name">
                          {manualPreviewFiles.length
                            ? `已选择 ${manualPreviewFiles.length} 张预览图`
                            : `单张 ≤ 5MB，至少 ${isRequestResponse ? MIN_REQUEST_PREVIEW_IMAGES : MIN_MANUAL_PREVIEW_IMAGES} 张`}
                        </span>
                        {manualPreviewFiles.length > 0 && (
                          <button type="button" className="file-clear" onClick={clearManualPreviewFiles} aria-label="清空预览图">
                            x
                          </button>
                        )}
                        <input
                          type="file"
                          ref={manualPreviewInputRef}
                          accept="image/*"
                          multiple
                          onChange={(e) => handleManualPreviewSelection(e.target.files)}
                        />
                      </div>
                      {manualPreviewFiles.length > 0 && (
                        <div className="inline-group wrap" style={{ marginTop: 8 }}>
                          {manualPreviewFiles.map((file, index) => (
                            <span key={`${file.name}-${index}`} className="badge-outline">
                              {file.name}
                              <button
                                type="button"
                                className="file-clear"
                                onClick={() => removeManualPreviewFile(index)}
                                aria-label={`移除 ${file.name}`}
                              >
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                      {manualPreviewNotice && <p className="error-text">{manualPreviewNotice}</p>}
                      <p className="help-text">预览图将自动压缩并生成省流版本，展示更快。</p>
                    </div>
                  )}
                  <label className="choice">
                    <input
                      type="checkbox"
                      checked={previewWatermarkEnabled}
                      onChange={(e) => setPreviewWatermarkEnabled(e.target.checked)}
                    />
                    <span>预览图加水印（单张≤5MB）</span>
                  </label>
                  <p className="help-text">可选。关闭后将生成无水印预览图。</p>
                </div>
              )}
              {isQuickMode && (
                <div className="form-item full">
                  <SectionLabel text="预览水印" optional />
                  <label className="choice">
                    <input
                      type="checkbox"
                      checked={previewWatermarkEnabled}
                      onChange={(e) => setPreviewWatermarkEnabled(e.target.checked)}
                    />
                    <span>预览图加水印（单张≤5MB）</span>
                  </label>
                </div>
              )}
              {deliveryMethod === 'FILE' && (
                <UploadMaterialFileField
                  file={zipFile}
                  sourceCount={zipSourceCount}
                  preparing={zipPreparing}
                  isEditing={isEditing}
                  placeholder={zipPlaceholder}
                  title={title}
                  maxTitleLength={MAX_TITLE_LENGTH}
                  inputRef={zipInputRef}
                  uploadProgress={uploadProgress}
                  onFilesSelected={handleZipSelection}
                  onClear={clearZipFile}
                />
              )}
              {deliveryMethod === 'NETDISK' && (
                <>
                  <div className="form-item full">
                    <SectionLabel htmlFor="netdiskUrl" text="网盘链接" />
                    <input
                      id="netdiskUrl"
                      type="text"
                      value={netdiskUrl}
                      onChange={(e) => setNetdiskUrl(e.target.value)}
                      placeholder="可粘贴任何网盘/私有链接或说明"
                      required
                    />
                    <p className="help-text">请确保链接长期可用，如有更新请及时维护。</p>
                  </div>
                  <div className="form-item">
                    <SectionLabel htmlFor="netdiskPassword" text="提取码" optional />
                    <input
                      id="netdiskPassword"
                      value={netdiskPassword}
                      onChange={(e) => setNetdiskPassword(e.target.value)}
                      placeholder="如有则填写"
                    />
                  </div>
                </>
              )}
            </div>
          </section>
        </div>
      )}

      <UploadConfirmSection
        isEditing={isEditing}
        isExperience={isExperience}
        isQuickMode={isQuickMode}
        copyrightOwner={copyrightOwner}
        maxCopyrightLength={MAX_COPYRIGHT_LENGTH}
        submitting={submitting}
        submissionStage={submissionStage}
        uploadProgress={uploadProgress}
        successPath={successPath}
        agreementAccepted={agreementAccepted}
        status={status}
        onCopyrightOwnerChange={setCopyrightOwner}
        onPolicyOpen={() => setPolicyModalOpen(true)}
        onAgreementAcceptedChange={setAgreementAccepted}
      />
    </form>
  );

  return (
    <>
      <NavBar user={user} />
      <main className="container upload-page">
        {!user ? (
          <section className="card upload-card">
            <h2>投稿中心 ✍️</h2>
            <p>
              需要先登录才能投稿，
              <Link className="login-link" href="/login">
                前往登录
              </Link>
              。
            </p>
          </section>
        ) : loadingExisting ? (
          <section className="card upload-card">
            <h2>投稿中心 ✍️</h2>
            <p>正在加载资料信息...</p>
          </section>
        ) : (
          <div className="upload-layout">
            <UploadProgressSidebar
              items={uploadNavItems}
              activeSection={activeSection}
              completion={sectionCompletion}
              onJump={jumpToSection}
            />
            <div className="upload-main">
              <UploadHero
                isEditing={isEditing}
                isRequestResponse={isRequestResponse}
                uploadMode={uploadMode}
                pageTitle={pageTitle}
                experienceHeading={experienceHeading}
                resolvedExperienceExtraTag={resolvedExperienceExtraTag}
                quickPanelOpen={quickPanelOpen}
                quickSelectedOption={quickSelectedOption}
                quickUploadOptions={QUICK_UPLOAD_OPTIONS}
                onSwitchUploadMode={switchUploadMode}
                onToggleQuickPanel={toggleQuickPanel}
                onQuickOptionSelect={handleQuickOptionSelect}
              />
              {formContent}
            </div>
          </div>
        )}
      </main>
      {policyModalOpen && <UploadPolicyModal onClose={() => setPolicyModalOpen(false)} />}
    </>
  );
}

export const getServerSideProps: GetServerSideProps<UploadPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const origin = getRequestOrigin(ctx.req);
  let account: UserAccountProfile | null = null;
  if (session.token) {
    try {
      account = await fetchAccountProfile(session.token, origin);
    } catch {
      account = null;
    }
  }
  return {
    props: {
      user: session.user,
      token: session.token,
      account,
    },
  };
};
