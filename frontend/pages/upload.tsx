import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import JSZip from 'jszip';
import NavBar from '../components/NavBar';
import { readSession } from '../lib/auth';
import { SessionUser } from '../types/user';
import { MaterialDetail } from '../types/material';
import { UserAccountProfile } from '../types/userProfile';
import {
  SUPPORTED_SCHOOL,
  SUPPORTED_COLLEGES,
  SUPPORTED_MAJORS,
  defaultCollege,
  COURSE_CATEGORY_OPTIONS,
  CourseCategoryValue,
  normalizeCourseCategory,
  GRADE_STAGE_OPTIONS,
} from '../constants/metadata';
import { fetchAccountProfile } from '../lib/api';
import { getRequestOrigin } from '../lib/apiBase';
import {
  ColumnTopicKey,
  getColumnTopicExtraTag,
  getColumnTopicTitle,
  isCommunityColumnTopic,
  normalizeColumnTopic,
  resolveExperienceTopicFromTags,
} from '../lib/column';
import { resolveApiBase } from '../lib/apiBase';
import { parseMajorList, serializeMajorList } from '../lib/major';
import { materialPath } from '../lib/slug';

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
  { id: 'upload-overview', label: '页面总览' },
  { id: 'upload-basic', label: '基础信息' },
  { id: 'upload-meta', label: '课程与标签' },
  { id: 'upload-delivery', label: '交付与预览' },
  { id: 'upload-confirm', label: '发布确认' },
];

const sanitizeFilename = (value: string) =>
  value
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, ' ')
    .trim();

const sanitizePriceInput = (value: string) => value.replace(/[^\d]/g, '');

const normalizePriceInput = (value: string) => {
  const cleaned = sanitizePriceInput(value);
  if (!cleaned) return '0';
  return cleaned.replace(/^0+(?=\\d)/, '');
};

const parsePriceValue = (value: string) => {
  const normalized = normalizePriceInput(value);
  if (!/^\d+$/.test(normalized)) return null;
  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed) || parsed < 0) return null;
  return parsed;
};

const formatPriceSummary = (value: string) => {
  const parsed = parsePriceValue(value);
  if (parsed === null) return '';
  return parsed === 0 ? '当前：免费' : `当前：¥${parsed}`;
};

const SectionLabel = ({ text, htmlFor, optional }: { text: string; htmlFor?: string; optional?: boolean }) => (
  <label htmlFor={htmlFor} className="section-label">
    <span className="section-marker" aria-hidden="true" />
    <span>{text}</span>
    {optional && <span className="optional-pill">可选</span>}
  </label>
);

const UploadTitleIcon = () => (
  <span className="upload-title-icon" aria-hidden="true">
    <svg viewBox="0 0 24 24" role="img" focusable="false">
      <path d="M3.5 7.5L12 3l8.5 4.5L12 12z" />
      <path d="M3.5 12L12 16.5 20.5 12" />
      <path d="M3.5 16.5L12 21l8.5-4.5" />
    </svg>
  </span>
);

interface UploadPageProps {
  user: SessionUser | null;
  token: string | null;
  account: UserAccountProfile | null;
}

const resolveMaterialProfilePrefill = (account: UserAccountProfile | null) => {
  const accountSchool = account?.school?.trim();
  const accountCollege = account?.college?.trim();
  const accountMajor = account?.major?.trim();
  const accountGrades = Array.isArray(account?.gradeStages) ? account.gradeStages.filter(Boolean) : [];
  const matchedGrade =
    accountGrades.find((stage) => GRADE_STAGE_OPTIONS.includes(stage as (typeof GRADE_STAGE_OPTIONS)[number])) || '';
  const resolvedMajors = accountMajor ? parseMajorList(accountMajor) : [];
  const hasProfileContext = Boolean(accountSchool || accountCollege || accountMajor || matchedGrade);
  if (!hasProfileContext) {
    return {
      school: SUPPORTED_SCHOOL,
      college: defaultCollege,
      majors: [] as string[],
      gradeValue: GRADE_STAGE_OPTIONS[0],
      courseCategory: 'MAJOR' as CourseCategoryValue,
    };
  }
  const resolvedCourseCategory: CourseCategoryValue =
    accountCollege || resolvedMajors.length > 0 ? 'MAJOR' : 'GENERAL';
  return {
    school: SUPPORTED_SCHOOL,
    college: resolvedCourseCategory === 'MAJOR' ? accountCollege || defaultCollege : '',
    majors: resolvedCourseCategory === 'MAJOR' ? resolvedMajors : [],
    gradeValue: matchedGrade || GRADE_STAGE_OPTIONS[0],
    courseCategory: resolvedCourseCategory,
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
  const [courseCategory, setCourseCategory] = useState<CourseCategoryValue>(materialProfilePrefill.courseCategory);
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
  const [manualPreviewFiles, setManualPreviewFiles] = useState<File[]>([]);
  const [manualPreviewNotice, setManualPreviewNotice] = useState<string | null>(null);
  const previewInputRef = useRef<HTMLInputElement | null>(null);
  const [customPreviewText, setCustomPreviewText] = useState('');
  const [customPreviewFiles, setCustomPreviewFiles] = useState<File[]>([]);
  const [customPreviewNotice, setCustomPreviewNotice] = useState<string | null>(null);
  const [customPreviewClear, setCustomPreviewClear] = useState(false);
  const [existingCustomPreviewImages, setExistingCustomPreviewImages] = useState<string[]>([]);
  const customPreviewInputRef = useRef<HTMLInputElement | null>(null);
  const [requestPreviewRequirement, setRequestPreviewRequirement] = useState('');
  const [hasExistingFile, setHasExistingFile] = useState(false);
  const [netdiskUrl, setNetdiskUrl] = useState('');
  const [netdiskPassword, setNetdiskPassword] = useState('');
  const [netdiskExpiredAt, setNetdiskExpiredAt] = useState('');
  const [netdiskReminderAt, setNetdiskReminderAt] = useState('');
  const [copyrightOwner, setCopyrightOwner] = useState('');
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loadingExisting, setLoadingExisting] = useState(false);
  const [zipPlaceholder, setZipPlaceholder] = useState('未选择任何文件');
  const [quickPanelOpen, setQuickPanelOpen] = useState(false);
  const [quickSelectedOption, setQuickSelectedOption] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<number | null>(null);
  const [requestPrefilled, setRequestPrefilled] = useState(false);
  const [activeSection, setActiveSection] = useState('upload-overview');
  const uploadRequestRef = useRef<XMLHttpRequest | null>(null);
  const apiBase = useMemo(
    () => resolveApiBase(typeof window !== 'undefined' ? window.location.origin : undefined),
    []
  );
  const isExperience = uploadMode === 'experience';
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
    experienceTopic === 'leetcode' && experienceCustomTag.trim()
      ? experienceCustomTag.trim()
      : experienceTopicExtraTag;
  const isRequestResponse = !isEditing && requestId != null;
  const isQuickMode = !isEditing && uploadMode === 'material' && quickPanelOpen && !isRequestResponse;
  const uploadNavItems = useMemo(() => {
    if (isExperience) {
      return UPLOAD_NAV_ITEMS.filter((item) => item.id !== 'upload-delivery');
    }
    return UPLOAD_NAV_ITEMS;
  }, [isExperience]);
  const descriptionLimit = isExperience ? MAX_EXPERIENCE_LENGTH : MAX_DESC_LENGTH;
  const customPreviewTitle = isExperience ? '经验配图' : '自定义预览';
  const customPreviewLabel = isExperience ? '经验配图' : '自定义预览图';
  const customPreviewHint = isExperience
    ? '可选：最多上传 5 张配图，单张 ≤ 5MB，无水印。'
    : '可选：图文结合展示，文字最多 800 字，图片最多 5 张。';
  const priceSummary = useMemo(() => formatPriceSummary(price), [price]);
  const hasPayoutQr = Boolean(account?.payoutQrUrl);
  const experienceHeading = isExperienceCustomTopic
    ? '经验分享'
    : experienceTopic === 'experience'
      ? '经验分享'
      : experienceTopicTitle;
  const quickProfile = useMemo(() => {
    const accountSchool = account?.school?.trim();
    const accountCollege = account?.college?.trim();
    const accountMajor = account?.major?.trim();
    const accountGrades = Array.isArray(account?.gradeStages) ? account?.gradeStages.filter(Boolean) : [];
    const matchedGrade =
      accountGrades.find((stage) => GRADE_STAGE_OPTIONS.includes(stage as (typeof GRADE_STAGE_OPTIONS)[number])) ||
      '';
    const resolvedSchool = accountSchool || SUPPORTED_SCHOOL;
    const resolvedCollege = accountCollege || defaultCollege;
    const resolvedMajors = accountMajor ? parseMajorList(accountMajor) : [];
    const resolvedGradeValue = matchedGrade || gradeStageOptions[0];
    const resolvedCourseCategory: CourseCategoryValue =
      accountCollege || resolvedMajors.length > 0 ? 'MAJOR' : 'GENERAL';
    return {
      school: resolvedSchool,
      college: resolvedCollege,
      majors: resolvedMajors,
      majorDisplay: accountMajor || '未填写',
      gradeValue: resolvedGradeValue,
      courseCategory: resolvedCourseCategory,
      courseCategoryLabel: resolvedCourseCategory === 'MAJOR' ? '专业课' : '通识课',
    };
  }, [account, gradeStageOptions]);
  const deriveGradeType = (stage: string) => {
    if (stage === '研究生') return 'GR';
    if (stage === '英语' || stage === '技能') return 'SKILL';
    return 'UG';
  };

  useEffect(() => {
    if (!uploadNavItems.some((item) => item.id === activeSection)) {
      setActiveSection('upload-overview');
    }
  }, [uploadNavItems, activeSection]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const sections = uploadNavItems
      .map((item) => document.getElementById(item.id))
      .filter((item): item is HTMLElement => Boolean(item));
    if (!sections.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
        if (visible.length > 0) {
          setActiveSection(visible[0].target.id);
        }
      },
      { rootMargin: '-24% 0px -58% 0px', threshold: [0.12, 0.38, 0.72] }
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [uploadNavItems, isEditing, uploadMode, quickPanelOpen, isRequestResponse]);

  useEffect(() => {
    const loadMaterial = async () => {
      if (!isEditing || !editingId) return;
      setLoadingExisting(true);
      try {
        const headers: Record<string, string> = { Accept: 'application/json' };
        if (token) {
          headers.Authorization = `Bearer ${token}`;
        }
        const res = await fetch(`${apiBase}/materials/${editingId}`, { headers });
        const json = await res.json();
        if (!res.ok || !json.ok || !json.data) {
          throw new Error(json.msg || '无法获取资料信息');
        }
        const detail: MaterialDetail = json.data;
        setTitle(detail.title || '');
        setDescription(detail.description || '');
        const detailPrice = detail.price != null ? Math.round(detail.price) : 0;
        setPrice(detailPrice > 0 ? String(detailPrice) : '0');
        setSchool(detail.school === SUPPORTED_SCHOOL ? detail.school : SUPPORTED_SCHOOL);
        const normalizedCategory = normalizeCourseCategory(detail.courseCategory, detail.generalEducation);
        setCourseCategory(normalizedCategory);
        const lockDepartment = normalizedCategory !== 'MAJOR';
        setCollege(lockDepartment ? '' : detail.college || defaultCollege);
        const parsedMajors = parseMajorList(detail.major);
        setSelectedMajors(lockDepartment ? [] : parsedMajors);
        const resolvedGradeStage =
          detail.gradeValue && gradeStageOptions.includes(detail.gradeValue as (typeof gradeStageOptions)[number])
            ? detail.gradeValue
            : gradeStageOptions[0];
        setGradeValue(resolvedGradeStage);
        const resolvedTags = detail.tags || [];
        setSelectedTags(resolvedTags.slice(0, MAX_TAGS));
        setUploadMode(resolvedTags.includes('经验分享') ? 'experience' : 'material');
        const resolvedTopic = resolveExperienceTopicFromTags(resolvedTags);
        setExperienceTopic(resolvedTopic);
        if (resolvedTags.includes('经验分享')) {
          const extraCustomTag = resolvedTags.find(
            (tag) =>
              tag &&
              tag !== '经验分享' &&
              tag !== '保研面经' &&
              tag !== '求职面经' &&
              tag !== '考研攻略' &&
              tag !== '留学指南' &&
              tag !== '考研心得' &&
              tag !== '留学心得'
          );
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
        setPreviewSource(detail.previewSource === PREVIEW_SOURCE_MANUAL ? PREVIEW_SOURCE_MANUAL : PREVIEW_SOURCE_AUTO);
        setManualPreviewFiles([]);
        setCustomPreviewText(detail.customPreviewText || '');
        setExistingCustomPreviewImages(detail.customPreviewImages || []);
        setCustomPreviewFiles([]);
        setCustomPreviewNotice(null);
        setCustomPreviewClear(false);
      } catch (err: any) {
        setStatus({ type: 'error', message: err.message || '加载资料信息失败' });
      } finally {
        setLoadingExisting(false);
      }
    };
    loadMaterial();
  }, [isEditing, editingId, token, apiBase, gradeStageOptions]);

  const jumpToSection = (id: string) => {
    if (typeof window === 'undefined') return;
    const target = document.getElementById(id);
    if (!target) return;
    setActiveSection(id);
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  useEffect(() => {
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
  }, [previewSource]);

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
    const budgetValue =
      typeof router.query.budget === 'string' ? Number(router.query.budget) : NaN;
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
    clearManualPreviews();
    setStatus(null);
  }, [router.query.topic, isEditing]);

  useEffect(() => {
    if (isEditing || !isExperience) return;
    setCourseCategory('GENERAL');
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

  const handlePreviewSelection = (files: FileList | null) => {
    if (!files) return;
    setManualPreviewNotice(null);
    const next = [...manualPreviewFiles];
    const errors: string[] = [];
    Array.from(files).forEach((file) => {
      if (!file.type.startsWith('image/')) {
        errors.push(`${file.name} 不是图片格式`);
        return;
      }
      if (file.size > MAX_PREVIEW_IMAGE_BYTES) {
        errors.push(`${file.name} 超过 5MB`);
        return;
      }
      if (next.length >= MAX_PREVIEW_IMAGES) {
        errors.push(`最多上传 ${MAX_PREVIEW_IMAGES} 张预览图`);
        return;
      }
      next.push(file);
    });
    setManualPreviewFiles(next);
    if (previewInputRef.current) {
      previewInputRef.current.value = '';
    }
    if (errors.length) {
      setManualPreviewNotice(errors[0]);
    }
  };

  const removePreviewFile = (index: number) => {
    setManualPreviewFiles((prev) => prev.filter((_, idx) => idx !== index));
  };

  const clearManualPreviews = () => {
    setManualPreviewFiles([]);
    if (previewInputRef.current) {
      previewInputRef.current.value = '';
    }
  };

  const handleCustomPreviewSelection = (files: FileList | null) => {
    if (!files) return;
    setCustomPreviewNotice(null);
    setCustomPreviewClear(false);
    setExistingCustomPreviewImages([]);
    const next = [...customPreviewFiles];
    const errors: string[] = [];
    Array.from(files).forEach((file) => {
      if (!file.type.startsWith('image/')) {
        errors.push(`${file.name} 不是图片格式`);
        return;
      }
      if (file.size > MAX_PREVIEW_IMAGE_BYTES) {
        errors.push(`${file.name} 超过 5MB`);
        return;
      }
      if (next.length >= MAX_CUSTOM_PREVIEW_IMAGES) {
        errors.push(`最多上传 ${MAX_CUSTOM_PREVIEW_IMAGES} 张${customPreviewLabel}`);
        return;
      }
      next.push(file);
    });
    setCustomPreviewFiles(next);
    if (customPreviewInputRef.current) {
      customPreviewInputRef.current.value = '';
    }
    if (errors.length) {
      setCustomPreviewNotice(errors[0]);
    }
  };

  const removeCustomPreviewFile = (index: number) => {
    setCustomPreviewFiles((prev) => prev.filter((_, idx) => idx !== index));
  };

  const clearCustomPreviewFiles = () => {
    setCustomPreviewFiles([]);
    if (customPreviewInputRef.current) {
      customPreviewInputRef.current.value = '';
    }
  };

  const clearCustomPreviewAll = () => {
    setCustomPreviewText('');
    setCustomPreviewClear(true);
    setCustomPreviewNotice(null);
    setExistingCustomPreviewImages([]);
    clearCustomPreviewFiles();
  };

  const sendFormData = (
    url: string,
    method: 'POST' | 'PUT',
    formData: FormData,
    onProgress: (value: number) => void,
    requestRef: { current: XMLHttpRequest | null }
  ): Promise<any> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      requestRef.current = xhr;
      xhr.open(method, url);
      xhr.responseType = 'json';
      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      }
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        const percent = Math.round((event.loaded / event.total) * 100);
        onProgress(percent);
      };
      xhr.onload = () => {
        const response =
          xhr.response ||
          (() => {
            try {
              return JSON.parse(xhr.responseText);
            } catch (error) {
              return null;
            }
          })();
        if (xhr.status >= 200 && xhr.status < 300 && response?.ok) {
          onProgress(100);
          resolve(response);
          return;
        }
        reject(new Error(response?.msg || '投稿失败'));
      };
      xhr.onerror = () => reject(new Error('网络异常'));
      xhr.onabort = () => reject(new Error('上传已取消'));
      xhr.send(formData);
    });

  const handleZipSelection = async (fileList: FileList | null) => {
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
      const zipName = buildZipName(title, deriveAutoTitle(files[0].name));
      const zipped = await zipFiles(files, zipName);
      if (zipTaskRef.current !== taskId) return;
      setZipFile(zipped);
    } catch (error: any) {
      if (zipTaskRef.current !== taskId) return;
      setStatus({ type: 'error', message: error.message || '文件打包失败，请重试。' });
      clearZipFile();
    } finally {
      if (zipTaskRef.current === taskId) {
        setZipPreparing(false);
      }
    }
  };

  const handleZipDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (event.dataTransfer.files && event.dataTransfer.files.length > 0) {
      void handleZipSelection(event.dataTransfer.files);
      event.dataTransfer.clearData();
    }
  };

  const deriveAutoTitle = (name: string) => {
    const withoutExt = name.replace(/\.[^/.]+$/, '');
    return withoutExt.slice(0, MAX_TITLE_LENGTH);
  };

  const buildZipName = (titleValue: string, fallbackName: string) => {
    const base = sanitizeFilename(titleValue || fallbackName || '资料');
    const trimmed = base.slice(0, MAX_TITLE_LENGTH).trim() || '资料';
    const normalized = trimmed.replace(/\.zip$/i, '');
    return `${normalized}.zip`;
  };

  const resolveZipFileName = (file: File, titleValue: string) => {
    const fallback = file.name.replace(/\.zip$/i, '') || '资料';
    const zipName = buildZipName(titleValue, fallback);
    if (file.name === zipName) return file;
    return new File([file], zipName, {
      type: file.type || 'application/zip',
      lastModified: file.lastModified,
    });
  };

  const zipFiles = async (files: File[], zipName: string) => {
    const zip = new JSZip();
    files.forEach((file) => {
      zip.file(file.name, file);
    });
    const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } });
    if (blob.size > MAX_FILE_BYTES) {
      throw new Error('打包后的文件超过 50MB，请删除部分文件或改用网盘链接。');
    }
    return new File([blob], zipName, { type: 'application/zip', lastModified: Date.now() });
  };

  const zipMarkdownContent = async (titleValue: string, content: string) => {
    const zip = new JSZip();
    zip.file('experience.md', content);
    const zipName = buildZipName(titleValue, '经验分享');
    const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } });
    if (blob.size > MAX_FILE_BYTES) {
      throw new Error('内容过长，打包后超过 50MB。');
    }
    return new File([blob], zipName, { type: 'application/zip', lastModified: Date.now() });
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setStatus(null);
    if (!token) {
      setStatus({ type: 'error', message: '请先登录后再投稿。' });
      return;
    }
    if (isExperience && !description.trim()) {
      setStatus({ type: 'error', message: '请填写经验分享内容。' });
      return;
    }
    if (isExperience && isExperienceCustomTopic && !experienceCustomTag.trim()) {
      setStatus({ type: 'error', message: '请选择自定义标签时，请填写标签名称。' });
      return;
    }
    if (!isExperience && customTags.split(/[,，\s]+/).some((tag) => tag.trim() === '经验分享')) {
      setStatus({ type: 'error', message: '“经验分享”标签仅用于经验分享投稿。' });
      return;
    }
    if (zipPreparing) {
      setStatus({ type: 'error', message: '正在打包文件，请稍后再提交。' });
      return;
    }
    const fallbackGradeValue = gradeStageOptions[0];
    const effectiveTitle = (title.trim() || (isQuickMode && zipFile ? deriveAutoTitle(zipFile.name) : '')).slice(
      0,
      MAX_TITLE_LENGTH
    );
    const effectiveGradeValue = isQuickMode ? quickProfile.gradeValue || fallbackGradeValue : gradeValue;
    const effectiveCourseCategory = isQuickMode ? quickProfile.courseCategory : courseCategory;
    const effectiveCollege = effectiveCourseCategory === 'MAJOR' ? (isQuickMode ? quickProfile.college : college) : '';
    const effectiveMajors = effectiveCourseCategory === 'MAJOR' ? (isQuickMode ? quickProfile.majors : selectedMajors) : [];
    const effectiveTagList = isQuickMode ? [] : tagList;
    const trimmedNetdiskUrl = netdiskUrl.trim();
    const resolvedDelivery = isExperience ? 'FILE' : deliveryMethod === 'NETDISK' ? 'NETDISK' : 'FILE';
    if (!isExperience && resolvedDelivery === 'FILE' && !zipFile && !hasExistingFile) {
      setStatus({ type: 'error', message: '请上传 50MB 以内的资料文件。' });
      return;
    }
    if (!isExperience && resolvedDelivery === 'NETDISK' && !trimmedNetdiskUrl) {
      setStatus({ type: 'error', message: '使用网盘链接时请填写链接地址。' });
      return;
    }
    const effectivePreviewSource = isExperience
      ? PREVIEW_SOURCE_AUTO
      : isRequestResponse
        ? PREVIEW_SOURCE_MANUAL
        : isQuickMode
          ? PREVIEW_SOURCE_AUTO
          : previewSource;
    if (!isExperience && effectivePreviewSource === PREVIEW_SOURCE_MANUAL) {
      const minRequired = isRequestResponse ? MIN_REQUEST_PREVIEW_IMAGES : MIN_MANUAL_PREVIEW_IMAGES;
      if (!isEditing && manualPreviewFiles.length < minRequired) {
        setStatus({ type: 'error', message: `请至少上传 ${minRequired} 张预览图。` });
        return;
      }
      if (manualPreviewFiles.length > 0 && manualPreviewFiles.length < minRequired) {
        setStatus({ type: 'error', message: `预览图数量不足（至少 ${minRequired} 张）。` });
        return;
      }
      const oversized = manualPreviewFiles.find((file) => file.size > MAX_PREVIEW_IMAGE_BYTES);
      if (oversized) {
        setStatus({ type: 'error', message: `预览图 ${oversized.name} 超过 5MB。` });
        return;
      }
    }
    if (!isExperience && !isQuickMode && customPreviewText.trim().length > MAX_CUSTOM_PREVIEW_TEXT) {
      setStatus({ type: 'error', message: `自定义预览文字需在 ${MAX_CUSTOM_PREVIEW_TEXT} 字以内。` });
      return;
    }
    if (!isQuickMode && customPreviewFiles.length > MAX_CUSTOM_PREVIEW_IMAGES) {
      setStatus({ type: 'error', message: `${customPreviewLabel}最多上传 ${MAX_CUSTOM_PREVIEW_IMAGES} 张。` });
      return;
    }
    const customOversized =
      !isQuickMode && customPreviewFiles.find((file) => file.size > MAX_PREVIEW_IMAGE_BYTES);
    if (customOversized) {
      setStatus({ type: 'error', message: `${customPreviewLabel} ${customOversized.name} 超过 5MB。` });
      return;
    }
    if (!effectiveTitle) {
      setStatus({
        type: 'error',
        message: isQuickMode ? '请填写资料标题或上传文件以自动生成标题。' : '请填写资料标题。',
      });
      return;
    }
    if (effectiveTitle.length > MAX_TITLE_LENGTH) {
      setStatus({ type: 'error', message: `标题需在 ${MAX_TITLE_LENGTH} 个字符以内。` });
      return;
    }
    if ((description || '').length > descriptionLimit) {
      setStatus({
        type: 'error',
        message: isExperience
          ? `经验分享内容需在 ${MAX_EXPERIENCE_LENGTH} 个字符以内。`
          : `资料简介需在 ${MAX_DESC_LENGTH} 个字符以内。`,
      });
      return;
    }
    if (!isQuickMode && copyrightOwner.trim().length > MAX_COPYRIGHT_LENGTH) {
      setStatus({ type: 'error', message: `版权持有者需在 ${MAX_COPYRIGHT_LENGTH} 个字符以内。` });
      return;
    }
    const priceValue = isExperience ? 0 : parsePriceValue(price);
    if (!isExperience && priceValue === null) {
      setStatus({ type: 'error', message: '价格需为正整数，免费请填 0。' });
      return;
    }
    const resolvedPriceValue = priceValue ?? 0;
    try {
      setSubmitting(true);
      setUploadProgress(isExperience || zipFile ? 0 : null);
      const trimmedTitle = effectiveTitle;
      const trimmedDescription = description.trim();
      const trimmedCustomPreviewText = isExperience || isQuickMode ? '' : customPreviewText.trim();
      const payload = {
        title: trimmedTitle,
        description: trimmedDescription,
        price: resolvedPriceValue * 100,
        school: isQuickMode ? quickProfile.school : SUPPORTED_SCHOOL,
        college: effectiveCollege,
        major: effectiveMajors.length > 0 ? serializeMajorList(effectiveMajors) : '',
        gradeValue: effectiveGradeValue,
        gradeType: deriveGradeType(effectiveGradeValue),
        generalCourse: effectiveCourseCategory === 'GENERAL',
        courseCategory: effectiveCourseCategory,
        tags: effectiveTagList.join(','),
        deliveryMethod: resolvedDelivery,
        netdiskUrl: isExperience ? null : trimmedNetdiskUrl || null,
        netdiskPassword: isExperience ? null : netdiskPassword.trim() || null,
        netdiskExpiredAt: isExperience ? null : netdiskExpiredAt || null,
        netdiskReminderAt: isExperience ? null : netdiskReminderAt || null,
        previewWatermarkEnabled,
        previewSource: effectivePreviewSource,
        customPreviewText: trimmedCustomPreviewText || null,
        copyrightOwner: isExperience || isQuickMode ? null : copyrightOwner.trim() || null,
      };
      if (!isEditing && requestId) {
        (payload as Record<string, unknown>).requestId = requestId;
      }
      if (isEditing) {
        (payload as Record<string, unknown>).customPreviewClear = customPreviewClear;
      }
      const formData = new FormData();
      let uploadFile =
        zipFile && zipSourceCount > 1 ? resolveZipFileName(zipFile, trimmedTitle) : zipFile;
      if (isExperience) {
        setZipPreparing(true);
        try {
          uploadFile = await zipMarkdownContent(trimmedTitle, trimmedDescription);
        } finally {
          setZipPreparing(false);
        }
      }
      formData.append('payload', new Blob([JSON.stringify(payload)], { type: 'application/json' }));
      if (uploadFile) {
        formData.append('zip', uploadFile);
      }
      if (!isExperience && !isQuickMode && effectivePreviewSource === PREVIEW_SOURCE_MANUAL) {
        manualPreviewFiles.forEach((file) => formData.append('previews', file));
      }
      if (!isQuickMode && customPreviewFiles.length > 0) {
        customPreviewFiles.forEach((file) => formData.append('customPreviews', file));
      }
      const endpoint = isEditing ? `${apiBase}/materials/${editingId}` : `${apiBase}/materials`;
      const method = isEditing ? 'PUT' : 'POST';
      const json = uploadFile
        ? await sendFormData(endpoint, method, formData, setUploadProgress, uploadRequestRef)
        : await (async () => {
            const res = await fetch(endpoint, {
              method,
              headers: {
                Authorization: `Bearer ${token}`,
              },
              body: formData,
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
              throw new Error(data.msg || '投稿失败');
            }
            return data;
          })();
      if (isQuickMode && !title.trim()) {
        setTitle(trimmedTitle);
      }
      setStatus({ type: 'success', message: isEditing ? '更新成功，正在跳转...' : '投稿成功，正在跳转到资料详情...' });
      await router.push(materialPath(json.data.id, json.data.title || trimmedTitle));
    } catch (error: any) {
      setStatus({ type: 'error', message: error.message || '投稿失败' });
    } finally {
      setSubmitting(false);
      setUploadProgress(null);
      uploadRequestRef.current = null;
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
      clearManualPreviews();
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
    <form className="upload-stacked-form" onSubmit={handleSubmit}>
      <div className="upload-section-shell" id="upload-basic">
        <div className="upload-section-heading">
          <div className="upload-section-heading__copy">
            <h2 className="upload-section-heading__title">基础信息</h2>
          </div>
        </div>
        <section className="card upload-main-card upload-section-card">
          <div className="form-grid upload-section-grid">
          <div className="form-item full">
            <SectionLabel
              htmlFor="title"
              text={isExperience ? `${experienceHeading}标题` : '资料标题'}
              optional={isQuickMode}
            />
            <input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required={!isQuickMode}
              placeholder={isQuickMode ? '可留空，系统将优先使用文件名自动生成标题' : undefined}
            />
            <p className="help-text">
              {isQuickMode
                ? `标题可留空；如已上传文件会自动生成，当前：${title.length}`
                : `标题需在 ${MAX_TITLE_LENGTH} 个字符以内，当前：${title.length}`}
            </p>
          </div>
          {!isQuickMode && (
            <div className="form-item full">
            <SectionLabel
              htmlFor="description"
              text={isExperience ? `${experienceHeading}内容` : '资料简介'}
              optional={!isExperience}
            />
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={isExperience ? '写下你的经验分享，支持 Markdown 语法' : '支持 Markdown 语法'}
              maxLength={descriptionLimit}
              required={isExperience}
            />
            <p className="help-text">
              {isExperience
                ? `内容支持 Markdown 语法，当前：${description.length}`
                : `资料简介需在 ${descriptionLimit} 个字符以内，当前：${description.length}`}
            </p>
            </div>
          )}
          {isExperience && (
            <div className="form-item full">
              <SectionLabel text={customPreviewTitle} optional />
              <p className="help-text">{customPreviewHint}</p>
              <div
                className="file-field drop-zone"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  handleCustomPreviewSelection(e.dataTransfer.files);
                }}
              >
                <span className="file-trigger">选择{customPreviewLabel}</span>
                <span className="file-name">
                  {customPreviewFiles.length
                    ? `已选择 ${customPreviewFiles.length} 张配图`
                    : `单张 ≤ 5MB，最多 ${MAX_CUSTOM_PREVIEW_IMAGES} 张`}
                </span>
                {customPreviewFiles.length > 0 && (
                  <button type="button" className="file-clear" onClick={clearCustomPreviewFiles} aria-label="清空配图">
                    x
                  </button>
                )}
                <input
                  type="file"
                  ref={customPreviewInputRef}
                  accept="image/*"
                  multiple
                  onChange={(e) => handleCustomPreviewSelection(e.target.files)}
                />
              </div>
              {customPreviewFiles.length > 0 && (
                <div className="inline-group wrap" style={{ marginTop: 8 }}>
                  {customPreviewFiles.map((file, index) => (
                    <span key={`${file.name}-${index}`} className="badge-outline">
                      {file.name}
                      <button
                        type="button"
                        className="file-clear"
                        onClick={() => removeCustomPreviewFile(index)}
                        aria-label={`移除 ${file.name}`}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
              {customPreviewNotice && <p className="error-text">{customPreviewNotice}</p>}
              {existingCustomPreviewImages.length > 0 && customPreviewFiles.length === 0 && (
                <div className="custom-preview-existing">
                  <p className="help-text">已存在 {existingCustomPreviewImages.length} 张配图。</p>
                  <div className="custom-preview-existing__grid">
                    {existingCustomPreviewImages.map((url, index) => (
                      <img key={`${url}-${index}`} src={url} alt={`已上传配图 ${index + 1}`} loading="lazy" />
                    ))}
                  </div>
                </div>
              )}
              {(customPreviewFiles.length > 0 || existingCustomPreviewImages.length > 0) && (
                <button type="button" className="text-button" onClick={clearCustomPreviewAll}>
                  清空配图
                </button>
              )}
            </div>
          )}
          {!isExperience && (
            <div className="form-item full">
              <SectionLabel htmlFor="price" text="价格（元）" />
              <input
                id="price"
                value={price}
                inputMode="numeric"
                pattern="[0-9]*"
                placeholder="0"
                onChange={(e) => setPrice(sanitizePriceInput(e.target.value))}
                onBlur={() => setPrice(normalizePriceInput(price))}
              />
              {priceSummary && <p className="help-text">默认免费；{priceSummary}</p>}
              <div className={`upload-price-payout-tip ${hasPayoutQr ? 'is-ready' : 'is-missing'}`}>
                <div className="upload-price-payout-tip__text">
                  {hasPayoutQr
                    ? '已检测到你已上传个人收款码，可直接投稿。'
                    : '你还未上传个人收款码，建议先补充，方便后续收益打款。'}
                </div>
                {!hasPayoutQr && (
                  <Link className="button ghost small upload-price-payout-tip__action" href="/me#profile">
                    去上传
                  </Link>
                )}
              </div>
            </div>
          )}
          </div>
        </section>
      </div>

      <div className="upload-section-shell" id="upload-meta">
        <div className="upload-section-heading">
          <div className="upload-section-heading__copy">
            <h2 className="upload-section-heading__title">课程与标签</h2>
          </div>
        </div>
        <section className="card upload-main-card upload-section-card">
          <div className="form-grid upload-section-grid">
          {isExperience ? (
            <div className="form-item full">
              <div className="upload-meta-empty">
                <p className="help-text">
                  经验分享标签为系统固定标签，所有分享都会自动附加。
                </p>
                <p className="help-text">可选择投稿到保研面经、求职面经、考研攻略、留学指南，或填写自定义标签归档到指定栏目。</p>
              </div>
              <div className="form-item full" style={{ marginTop: 12 }}>
                <SectionLabel text="投稿栏目" optional />
                <div className="inline-group wrap">
                  <label className={`choice-pill ${experienceTopic === 'experience' ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="experienceTopic"
                      value="experience"
                      checked={experienceTopic === 'experience'}
                      onChange={() => {
                        setExperienceTopic('experience');
                        setExperienceCustomTag('');
                      }}
                    />
                    <span>经验心得</span>
                  </label>
                  <label className={`choice-pill ${experienceTopic === 'grad-school' ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="experienceTopic"
                      value="grad-school"
                      checked={experienceTopic === 'grad-school'}
                      onChange={() => {
                        setExperienceTopic('grad-school');
                        setExperienceCustomTag('');
                      }}
                    />
                    <span>保研面经</span>
                  </label>
                  <label className={`choice-pill ${experienceTopic === 'career' ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="experienceTopic"
                      value="career"
                      checked={experienceTopic === 'career'}
                      onChange={() => {
                        setExperienceTopic('career');
                        setExperienceCustomTag('');
                      }}
                    />
                    <span>求职面经</span>
                  </label>
                  <label className={`choice-pill ${experienceTopic === 'postgrad-exam' ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="experienceTopic"
                      value="postgrad-exam"
                      checked={experienceTopic === 'postgrad-exam'}
                      onChange={() => {
                        setExperienceTopic('postgrad-exam');
                        setExperienceCustomTag('');
                      }}
                    />
                    <span>考研攻略</span>
                  </label>
                  <label className={`choice-pill ${experienceTopic === 'overseas' ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="experienceTopic"
                      value="overseas"
                      checked={experienceTopic === 'overseas'}
                      onChange={() => {
                        setExperienceTopic('overseas');
                        setExperienceCustomTag('');
                      }}
                    />
                    <span>留学指南</span>
                  </label>
                  <label className={`choice-pill ${isExperienceCustomTopic ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="experienceTopic"
                      value="custom"
                      checked={isExperienceCustomTopic}
                      onChange={() => setExperienceTopic('leetcode')}
                    />
                    <span>自定义标签</span>
                  </label>
                </div>
                {isExperienceCustomTopic && (
                  <div className="form-item full" style={{ marginTop: 10 }}>
                    <input
                      placeholder="填写自定义栏目标签（例如：考研经验 / 竞赛复盘）"
                      value={experienceCustomTag}
                      onChange={(e) => setExperienceCustomTag(e.target.value.replace(/\s+/g, ' ').slice(0, 16))}
                    />
                    <p className="help-text">自定义标签将与“经验分享”一起保存并用于专栏归档。</p>
                  </div>
                )}
              </div>
            </div>
          ) : isQuickMode ? (
            <div className="form-item full">
                <div className="upload-quick-summary">
                  <div className="upload-quick-summary__item">
                    <span className="upload-quick-summary__label">学校</span>
                    <strong className="upload-quick-summary__value">{quickProfile.school}</strong>
                  </div>
                  <div className="upload-quick-summary__item">
                    <span className="upload-quick-summary__label">年级/阶段</span>
                    <strong className="upload-quick-summary__value">{quickProfile.gradeValue}</strong>
                  </div>
                  <div className="upload-quick-summary__item">
                    <span className="upload-quick-summary__label">学院</span>
                    <strong className="upload-quick-summary__value">{quickProfile.college || '未填写'}</strong>
                  </div>
                  <div className="upload-quick-summary__item">
                    <span className="upload-quick-summary__label">专业</span>
                    <strong className="upload-quick-summary__value">{quickProfile.majorDisplay}</strong>
                  </div>
                  <div className="upload-quick-summary__item">
                    <span className="upload-quick-summary__label">课程类型</span>
                    <strong className="upload-quick-summary__value">{quickProfile.courseCategoryLabel}</strong>
                  </div>
                </div>
              <p className="help-text">一键投稿会优先使用“我的”里个人主页概览所填的学校、学院、专业与年级信息；未填写的字段将按默认值补齐。</p>
            </div>
          ) : (
            <>
              <div className="form-item">
                <SectionLabel htmlFor="school" text="学校" />
                <select id="school" value={school} onChange={(e) => setSchool(e.target.value)} required>
                  <option value={SUPPORTED_SCHOOL}>{SUPPORTED_SCHOOL}</option>
                </select>
              </div>
              <div className="form-item">
                <SectionLabel htmlFor="college" text="学院" />
                <select
                  id="college"
                  value={college}
                  onChange={(e) => setCollege(e.target.value)}
                  disabled={courseCategory !== 'MAJOR'}
                  required={courseCategory === 'MAJOR'}
                >
                  <option value="">{courseCategory === 'MAJOR' ? '请选择学院' : '无需选择'}</option>
                  {SUPPORTED_COLLEGES.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-item">
                <SectionLabel text="年级/阶段" />
                <select id="gradeValue" value={gradeValue} onChange={(e) => setGradeValue(e.target.value)}>
                  {gradeStageOptions.map((stage) => (
                    <option key={stage} value={stage}>
                      {stage}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-item">
                <SectionLabel text="专业" optional />
                <div className="inline-group wrap">
                  {SUPPORTED_MAJORS.map((name) => {
                    const checked = selectedMajors.includes(name);
                    return (
                      <label key={name} className={`choice badge-outline ${checked ? 'active' : ''}`}>
                        <input
                          type="checkbox"
                          value={name}
                          checked={checked}
                          disabled={courseCategory !== 'MAJOR'}
                          onChange={(e) => handleMajorToggle(name, e.target.checked)}
                        />
                        {name}
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="form-item full">
                <SectionLabel text="课程类型" />
                <div className="course-type-options upload-course-type-options">
                  {COURSE_CATEGORY_OPTIONS.map((option) => (
                    <label
                      key={option.value}
                      className={`choice-pill course upload-course-type-chip ${courseCategory === option.value ? 'active' : ''}`}
                    >
                      <input
                        type="radio"
                        name="courseCategory"
                        value={option.value}
                        checked={courseCategory === option.value}
                        onChange={(e) => setCourseCategory(e.target.value as CourseCategoryValue)}
                      />
                      <div>
                        <strong>{option.label}</strong>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
              <div className="form-item full">
                <SectionLabel text="标签" optional />
                <div className="inline-group wrap">
                  {presetTags.map((tag) => (
                    <label key={tag} className="choice badge-outline">
                      <input
                        type="checkbox"
                        checked={selectedTags.includes(tag)}
                        disabled={!selectedTags.includes(tag) && tagList.length >= MAX_TAGS}
                        onChange={(e) =>
                          setSelectedTags((prev) => {
                            const exists = prev.includes(tag);
                            if (e.target.checked) {
                              if (exists || tagList.length >= MAX_TAGS) {
                                return prev;
                              }
                              return [...prev, tag];
                            }
                            return prev.filter((item) => item !== tag);
                          })
                        }
                      />
                      {tag}
                    </label>
                  ))}
                </div>
                <input
                  placeholder="自定义标签，使用逗号或空格分隔（最多 3 个）"
                  value={customTags}
                  onChange={(e) => setCustomTags(e.target.value)}
                />
                <p className="help-text">
                  已选择 {tagList.length}/{MAX_TAGS} 个标签
                  {trimmedCustom ? '，多余的自定义标签将不会保存' : ''}
                </p>
                <div className="upload-year-field">
                  <SectionLabel text="资料年份" optional />
                  <div className="inline-group wrap">
                    <input
                      type="text"
                      list="year-options"
                      placeholder="可输入或选择：如 2023 / 2023-2024"
                      value={yearTag}
                      onChange={(e) => setYearTag(e.target.value)}
                    />
                    <datalist id="year-options">
                      {yearSuggestions.map((option) => (
                        <option key={option} value={option} />
                      ))}
                    </datalist>
                  </div>
                </div>
              </div>
            </>
          )}
          </div>
        </section>
      </div>

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
              <SectionLabel text="资料交付方式" />
              <div className="inline-group wrap delivery-toggle">
                <label className={`choice-pill ${deliveryMethod === 'FILE' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="deliveryMethod"
                    value="FILE"
                    checked={deliveryMethod === 'FILE'}
                    onChange={() => setDeliveryMethod('FILE')}
                  />
                  <span>上传文件（≤50MB）</span>
                </label>
                <label className={`choice-pill ${deliveryMethod === 'NETDISK' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="deliveryMethod"
                    value="NETDISK"
                    checked={deliveryMethod === 'NETDISK'}
                    onChange={() => setDeliveryMethod('NETDISK')}
                  />
                  <span>使用网盘链接</span>
                </label>
              </div>
              <p className="help-text">
                {isQuickMode
                  ? '一键投稿默认自动生成预览，仅保留文件交付与网盘链接两种方式。'
                  : '超过 50MB 或特殊格式的资料请改用网盘链接，确保链接长期有效。'}
              </p>
            </div>
            {!isQuickMode && (
              <div className="form-item full">
              <SectionLabel text="预览图设置" />
              {isRequestResponse ? (
                <p className="help-text">
                  请上传符合求购者要求的预览图
                  {requestPreviewRequirement ? `：${requestPreviewRequirement}` : '。'}
                </p>
              ) : (
                <>
                  <div className="inline-group wrap">
                    <label className={`choice-pill ${previewSource === PREVIEW_SOURCE_AUTO ? 'active' : ''}`}>
                      <input
                        type="radio"
                        name="previewSource"
                        value={PREVIEW_SOURCE_AUTO}
                        checked={previewSource === PREVIEW_SOURCE_AUTO}
                        onChange={() => setPreviewSource(PREVIEW_SOURCE_AUTO)}
                      />
                      <span>自动生成（推荐）</span>
                    </label>
                    <label className={`choice-pill ${previewSource === PREVIEW_SOURCE_MANUAL ? 'active' : ''}`}>
                      <input
                        type="radio"
                        name="previewSource"
                        value={PREVIEW_SOURCE_MANUAL}
                        checked={previewSource === PREVIEW_SOURCE_MANUAL}
                        onChange={() => setPreviewSource(PREVIEW_SOURCE_MANUAL)}
                      />
                      <span>手动上传</span>
                    </label>
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
                      handlePreviewSelection(e.dataTransfer.files);
                    }}
                  >
                    <span className="file-trigger">选择预览图</span>
                    <span className="file-name">
                      {manualPreviewFiles.length
                        ? `已选择 ${manualPreviewFiles.length} 张预览图`
                        : `单张 ≤ 5MB，至少 ${isRequestResponse ? MIN_REQUEST_PREVIEW_IMAGES : MIN_MANUAL_PREVIEW_IMAGES} 张`}
                    </span>
                    {manualPreviewFiles.length > 0 && (
                      <button type="button" className="file-clear" onClick={clearManualPreviews} aria-label="清空预览图">
                        x
                      </button>
                    )}
                    <input
                      type="file"
                      ref={previewInputRef}
                      accept="image/*"
                      multiple
                      onChange={(e) => handlePreviewSelection(e.target.files)}
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
                            onClick={() => removePreviewFile(index)}
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
            {!isQuickMode && (
              <div className="form-item full">
              <SectionLabel text={customPreviewTitle} optional />
              <p className="help-text">{customPreviewHint}</p>
              <textarea
                rows={5}
                value={customPreviewText}
                maxLength={MAX_CUSTOM_PREVIEW_TEXT}
                placeholder="写下这份资料的亮点、目录或适用场景（可选）"
                onChange={(e) => {
                  setCustomPreviewText(e.target.value);
                  setCustomPreviewClear(false);
                }}
              />
              <div className="help-text">已输入 {customPreviewText.length}/{MAX_CUSTOM_PREVIEW_TEXT}</div>
              <div
                className="file-field drop-zone"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  handleCustomPreviewSelection(e.dataTransfer.files);
                }}
              >
                <span className="file-trigger">选择{customPreviewLabel}</span>
                <span className="file-name">
                  {customPreviewFiles.length
                    ? `已选择 ${customPreviewFiles.length} 张预览图`
                    : `单张 ≤ 5MB，最多 ${MAX_CUSTOM_PREVIEW_IMAGES} 张`}
                </span>
                {customPreviewFiles.length > 0 && (
                  <button
                    type="button"
                    className="file-clear"
                    onClick={clearCustomPreviewFiles}
                    aria-label="清空自定义预览图"
                  >
                    x
                  </button>
                )}
                <input
                  type="file"
                  ref={customPreviewInputRef}
                  accept="image/*"
                  multiple
                  onChange={(e) => handleCustomPreviewSelection(e.target.files)}
                />
              </div>
              {customPreviewFiles.length > 0 && (
                <div className="inline-group wrap" style={{ marginTop: 8 }}>
                  {customPreviewFiles.map((file, index) => (
                    <span key={`${file.name}-${index}`} className="badge-outline">
                      {file.name}
                      <button
                        type="button"
                        className="file-clear"
                        onClick={() => removeCustomPreviewFile(index)}
                        aria-label={`移除 ${file.name}`}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
              {customPreviewNotice && <p className="error-text">{customPreviewNotice}</p>}
              {existingCustomPreviewImages.length > 0 && customPreviewFiles.length === 0 && (
                <div className="custom-preview-existing">
                  <p className="help-text">已存在 {existingCustomPreviewImages.length} 张自定义预览图。</p>
                  <div className="custom-preview-existing__grid">
                    {existingCustomPreviewImages.map((url, index) => (
                      <img key={`${url}-${index}`} src={url} alt={`已上传预览图 ${index + 1}`} loading="lazy" />
                    ))}
                  </div>
                </div>
              )}
              {(customPreviewText.trim() || customPreviewFiles.length > 0 || existingCustomPreviewImages.length > 0) && (
                <button type="button" className="text-button" onClick={clearCustomPreviewAll}>
                  清空自定义预览
                </button>
              )}
              </div>
            )}
            {deliveryMethod === 'FILE' && (
              <div className="form-item full">
                <SectionLabel htmlFor="zip" text="资料文件（总大小≤50MB，支持多文件）" />
                <div className="file-field drop-zone" onDragOver={(e) => e.preventDefault()} onDrop={handleZipDrop}>
                  <span className="file-trigger">选择文件</span>
                  <span className="file-name">
                    {zipPreparing
                      ? '正在打包文件...'
                      : zipFile
                        ? zipSourceCount > 1
                          ? `已选择 ${zipSourceCount} 个文件，打包为 ${buildZipName(
                              title,
                              zipFile.name.replace(/\.zip$/i, '')
                            )}`
                          : zipFile.name
                        : isEditing
                          ? '保持现有文件（可重新上传）'
                          : zipPlaceholder}
                  </span>
                  {zipFile && (
                    <button type="button" className="file-clear" onClick={clearZipFile} aria-label="移除文件">
                      x
                    </button>
                  )}
                  <input
                    id="zip"
                    type="file"
                    ref={zipInputRef}
                    multiple
                    onChange={(e) => void handleZipSelection(e.target.files)}
                  />
                </div>
                {uploadProgress !== null && (
                  <div className="upload-progress" aria-live="polite">
                    <progress value={uploadProgress} max={100} />
                    <span className="upload-percent">{uploadProgress}%</span>
                  </div>
                )}
                <p className="help-text">将文件拖拽到此区域或点击选择，总大小不超过 50MB，多文件将自动打包为 zip。</p>
              </div>
            )}
            <div className="form-item full">
              <SectionLabel htmlFor="netdiskUrl" text="网盘链接" optional={deliveryMethod !== 'NETDISK'} />
              <input
                id="netdiskUrl"
                type="text"
                value={netdiskUrl}
                onChange={(e) => setNetdiskUrl(e.target.value)}
                placeholder="可粘贴任何网盘/私有链接或说明"
                required={deliveryMethod === 'NETDISK'}
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
            </div>
          </section>
        </div>
      )}

      <div className="upload-section-shell" id="upload-confirm">
        <div className="upload-section-heading">
          <div className="upload-section-heading__copy">
            <h2 className="upload-section-heading__title">发布确认</h2>
          </div>
        </div>
        <section className="card upload-main-card upload-section-card">
          <div className="form-grid upload-section-grid">
          {!isExperience && !isQuickMode && (
            <div className="form-item full">
              <SectionLabel htmlFor="copyrightOwner" text="版权持有者" optional />
              <input
                id="copyrightOwner"
                value={copyrightOwner}
                onChange={(e) => setCopyrightOwner(e.target.value)}
                maxLength={MAX_COPYRIGHT_LENGTH}
                placeholder="不超过 8 个字符，如：张三"
              />
              <p className="help-text">
                若为学校官网或个人原创资料可不填；如来源于其他同学/渠道，请先征得同意再发布，并填写对方姓名。
              </p>
            </div>
          )}
          <div className="form-item full">
            <label className="choice agreement">
              <input type="checkbox" required />
              <span>
                我已阅读并同意
                <button
                  type="button"
                  className="policy-link"
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setPolicyModalOpen(true);
                  }}
                >
                  平台隐私政策/用户协议
                </button>
                ，确认资料合法且授权发布。平台运营初期由平台统一收费与分发，抽成比例暂定 30%，用于运营成本和维护；后续若有调整将提前公告，请知悉。
              </span>
            </label>
          </div>
          <div className="form-item">
            <button className="button primary" type="submit" disabled={submitting}>
              {submitting
                ? isEditing
                  ? '更新中...'
                  : '提交中...'
                : isEditing
                  ? isExperience
                    ? '更新经验分享'
                    : '更新资料'
                  : isExperience
                    ? '提交经验分享'
                    : isQuickMode
                      ? '一键投稿'
                      : '提交资料'}
            </button>
          </div>
          {isExperience && uploadProgress !== null && (
            <div className="form-item full">
              <div className="upload-progress" aria-live="polite">
                <progress value={uploadProgress} max={100} />
                <span className="upload-percent">{uploadProgress}%</span>
              </div>
            </div>
          )}
          {status && <p className={status.type === 'error' ? 'error-text' : 'success-text'}>{status.message}</p>}
          </div>
        </section>
      </div>
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
              <Link className="login-link" href="/login">前往登录</Link>。
            </p>
          </section>
        ) : loadingExisting ? (
          <section className="card upload-card">
            <h2>投稿中心 ✍️</h2>
            <p>正在加载资料信息...</p>
          </section>
        ) : (
          <div className="upload-layout">
            <aside className="me-sidebar upload-sidebar">
              <div className="me-sidebar__brand">投稿中心</div>
              <div className="me-sidebar__group">
                <div className="me-sidebar__label">页面导航</div>
                <nav className="me-sidebar__items" aria-label="投稿页面导航">
                  {uploadNavItems.map((item) => (
                    <a
                      key={item.id}
                      href={`#${item.id}`}
                      className={`me-sidebar__item${activeSection === item.id ? ' active' : ''}`}
                      onClick={(event) => {
                        event.preventDefault();
                        jumpToSection(item.id);
                      }}
                    >
                      <span className="me-sidebar__indicator" />
                      <span className="me-sidebar__text">{item.label}</span>
                    </a>
                  ))}
                </nav>
              </div>
            </aside>
            <div className="upload-main">
              <section className="card me-hero upload-hero" id="upload-overview">
                <div className="me-hero__inner">
                  <div className="me-hero__intro">
                    <div className="me-hero__eyebrow">{isEditing ? '编辑模式' : '投稿工作台'}</div>
                        <div className="me-hero__title-row">
                          <h1 className="me-hero__title upload-title">
                            <UploadTitleIcon />
                            <span>{pageTitle}</span>
                          </h1>
                        </div>
                        {uploadMode === 'experience' && (
                          <p className="me-hero__subtitle upload-hero__subtitle">
                            当前方向：{experienceHeading}
                            {resolvedExperienceExtraTag ? ` · 自动附加 #${resolvedExperienceExtraTag}` : ''}
                          </p>
                        )}
                    {!isEditing && !isRequestResponse && (
                      <div className="upload-hero__actions">
                        <div className="upload-hero__tools">
                          {uploadMode === 'experience' ? (
                            <>
                              <Link className="upload-hero__action upload-hero__action--secondary" href="/column">
                                <span className="upload-hero__action-label">返回学汇专栏</span>
                              </Link>
                              <button
                                type="button"
                                className="upload-hero__action upload-hero__action--secondary active"
                                onClick={() => switchUploadMode('material')}
                              >
                                <span className="upload-hero__action-label">返回资料投稿</span>
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                className={`upload-hero__action${quickPanelOpen ? ' active' : ''}`}
                                onClick={toggleQuickPanel}
                              >
                                <span className="upload-hero__action-label">
                                  {quickPanelOpen ? '收起一键投稿' : '太麻烦？一键投稿'}
                                </span>
                              </button>
                              <button
                                type="button"
                                className="upload-hero__action upload-hero__action--secondary"
                                onClick={() => switchUploadMode('experience')}
                              >
                                <span className="upload-hero__action-label">开始经验分享</span>
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                  {!isEditing && !isRequestResponse && QUICK_UPLOAD_OPTIONS.length > 0 && (
                    <div className="upload-hero__pills">
                      <div className="upload-option-pills">
                        {QUICK_UPLOAD_OPTIONS.map((option) => (
                          <button
                            key={option}
                            type="button"
                            className={`button ${quickSelectedOption === option ? 'primary' : 'ghost'} small`}
                            onClick={() => handleQuickOptionSelect(option)}
                          >
                            {option}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </section>
              {formContent}
            </div>
          </div>
        )}
      </main>
      {policyModalOpen && (
        <div className="modal-mask" onClick={() => setPolicyModalOpen(false)}>
          <div
            className="modal-card policy-modal"
            role="dialog"
            aria-modal="true"
            aria-label="平台隐私政策与用户协议"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="modal-close"
              type="button"
              aria-label="关闭"
              onClick={() => setPolicyModalOpen(false)}
            >
              ×
            </button>
            <h2>平台隐私政策/用户协议</h2>
            <h3>为什么需要身份信息？</h3>
            <p className="help-text">
              我们仅在<strong>提现</strong>等涉及向个人支付创作者收益的环节，要求填写姓名、身份证号及同名支付宝账号，主要基于两类需求：
            </p>
            <ol>
              <li>
                <strong>税务合规（依法扣缴申报）</strong>
                <p className="help-text">
                  当平台向个人支付所得时，通常需要依法履行个人所得税的扣缴申报义务。个人所得税法明确：扣缴义务人应当按照国家规定办理
                  <strong>全员全额扣缴申报</strong>。（
                  <a href="https://gongbao.court.gov.cn/Details/8387ed08755a9be653320a8fc12c8e.html" target="_blank" rel="noreferrer">[1]</a>
                  ）在扣缴申报制度下，扣缴义务人需要向税务机关报送包括<strong>姓名、证件信息等</strong>在内的个人基础信息、支付所得项目与数额等涉税信息。（
                  <a href="https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193745/content.html" target="_blank" rel="noreferrer">[2]</a>
                  ）关于自然人纳税人识别号的规定/解读也强调：自然人首次办理涉税事项时，需要向税务机关或扣缴义务人提供有效身份证件及相关信息。（
                  <a href="https://shanghai.chinatax.gov.cn/zcfw/zcjd/201812/t443337.html" target="_blank" rel="noreferrer">[3]</a>
                  ）
                </p>
              </li>
              <li>
                <strong>打款成功与安全（同名校验与防冒领）</strong>
                <p className="help-text">
                  同名支付宝信息用于减少转账失败、退回等情况，并降低冒领、盗刷、异常提现风险。
                </p>
              </li>
            </ol>
            <h3>身份信息如何使用与保护</h3>
            <h4>使用范围（用途限制）</h4>
            <ul>
              <li>税务扣缴申报与合规留存（按规定报送必要的个人基础信息与所得信息）。</li>
              <li>提现审核与打款校验（核验收款人实名信息与同名支付宝）。</li>
              <li>风控与纠纷处理（异常提现、申诉、争议仲裁时用于核验与审计）。</li>
            </ul>
            <h4>保护措施（合规要求）</h4>
            <p className="help-text">
              我们遵循《个人信息保护法》的基本要求：以<strong>明确目的、最小必要</strong>方式收集，公开透明说明用途，并采取必要安全措施。包括但不限于：加密存储、脱敏展示、权限控制、访问留痕与审计。（
              <a href="https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm" target="_blank" rel="noreferrer">[4]</a>
              ）
            </p>
            <h3>谁能看到我的信息？</h3>
            <ul>
              <li>✅ 可见范围：仅限与提现审核、税务申报/对账、风控合规相关的人员在履职范围内查看。</li>
              <li>❌ 不可见范围：其他普通用户、购买者、非相关岗位人员均不可见。</li>
              <li>
                ✅ 访问可追溯：对敏感信息的访问会记录日志，用于安全审计与责任追踪。（
                <a href="https://npcobserver.com/wp-content/uploads/2023/09/2021-Personal-Information-Protection-Law_Gazette.pdf" target="_blank" rel="noreferrer">[5]</a>
                ）
              </li>
            </ul>
            <h4>参考链接</h4>
            <ul>
              <li>
                <a href="https://gongbao.court.gov.cn/Details/8387ed08755a9be653320a8fc12c8e.html" target="_blank" rel="noreferrer">
                  [1] 中华人民共和国个人所得税法（公报网）
                </a>
              </li>
              <li>
                <a href="https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193745/content.html" target="_blank" rel="noreferrer">
                  [2] 国家税务总局关于印发《个人所得税全员全额扣缴申报管理》相关内容
                </a>
              </li>
              <li>
                <a href="https://shanghai.chinatax.gov.cn/zcfw/zcjd/201812/t443337.html" target="_blank" rel="noreferrer">
                  [3] 自然人纳税人识别号有关事项解读（上海税务）
                </a>
              </li>
              <li>
                <a href="https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm" target="_blank" rel="noreferrer">
                  [4] 中华人民共和国个人信息保护法（国家网信办）
                </a>
              </li>
              <li>
                <a href="https://npcobserver.com/wp-content/uploads/2023/09/2021-Personal-Information-Protection-Law_Gazette.pdf" target="_blank" rel="noreferrer">
                  [5] 个人信息保护法全文（NPC Observer）
                </a>
              </li>
            </ul>
          </div>
        </div>
      )}
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
