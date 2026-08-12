import Link from 'next/link';
import { Dispatch, SetStateAction } from 'react';
import {
  COURSE_CATEGORY_OPTIONS,
  CourseCategorySelection,
  CourseCategoryValue,
  SUPPORTED_SCHOOL,
  getCollegeOptions,
  getMajorOptionsForCollege,
} from '../../constants/metadata';
import { ColumnTopicKey } from '../../lib/column';
import UploadChoiceCard from './UploadChoiceCard';
import UploadSectionLabel from './UploadSectionLabel';

interface QuickProfile {
  school: string;
  college: string;
  majorDisplay: string;
  gradeValue: string;
}

interface UploadMetaSectionProps {
  isExperience: boolean;
  isQuickMode: boolean;
  isExperienceCustomTopic: boolean;
  experienceTopic: ColumnTopicKey;
  experienceCustomTag: string;
  quickProfile: QuickProfile;
  school: string;
  college: string;
  gradeValue: string;
  gradeStageOptions: readonly string[];
  selectedMajors: string[];
  courseCategory: CourseCategorySelection;
  selectedTags: string[];
  customTags: string;
  yearTag: string;
  yearSuggestions: string[];
  presetTags: string[];
  tagList: string[];
  maxTags: number;
  trimmedCustom: boolean;
  onExperienceTopicChange: Dispatch<SetStateAction<ColumnTopicKey>>;
  onExperienceCustomTagChange: (value: string) => void;
  onSchoolChange: (value: string) => void;
  onCollegeChange: (value: string) => void;
  onGradeValueChange: (value: string) => void;
  onMajorToggle: (name: string, checked: boolean) => void;
  onCourseCategoryChange: (value: CourseCategoryValue) => void;
  onSelectedTagsChange: Dispatch<SetStateAction<string[]>>;
  onCustomTagsChange: (value: string) => void;
  onYearTagChange: (value: string) => void;
}

export default function UploadMetaSection({
  isExperience,
  isQuickMode,
  isExperienceCustomTopic,
  experienceTopic,
  experienceCustomTag,
  quickProfile,
  school,
  college,
  gradeValue,
  gradeStageOptions,
  selectedMajors,
  courseCategory,
  selectedTags,
  customTags,
  yearTag,
  yearSuggestions,
  presetTags,
  tagList,
  maxTags,
  trimmedCustom,
  onExperienceTopicChange,
  onExperienceCustomTagChange,
  onSchoolChange,
  onCollegeChange,
  onGradeValueChange,
  onMajorToggle,
  onCourseCategoryChange,
  onSelectedTagsChange,
  onCustomTagsChange,
  onYearTagChange,
}: UploadMetaSectionProps) {
  const collegeOptions = getCollegeOptions(college);
  const majorOptions = Array.from(new Set([...selectedMajors, ...getMajorOptionsForCollege(college)]));
  return (
    <div className="upload-section-shell" id="upload-meta">
      <div className="upload-section-heading">
        <div className="upload-section-heading__copy">
          <div className="upload-section-heading__title-row">
            <h2 className="upload-section-heading__title">课程与标签</h2>
            <details className="upload-profile-help">
              <summary aria-label="查看课程信息默认值说明">?</summary>
              <div className="upload-profile-help__popover">
                <strong>默认信息从哪里来？</strong>
                <p>学校、学院、专业和年级会优先读取“我的”个人主页概览；本次投稿仍可单独调整。</p>
                <Link className="button ghost small" href="/me#profile" prefetch={false}>
                  前往个人主页修改
                </Link>
              </div>
            </details>
          </div>
        </div>
      </div>
      <section className="card upload-main-card upload-section-card">
        <div className="form-grid upload-section-grid">
          {!isExperience && (
            <div className="form-item full">
              <UploadSectionLabel text="课程类型" selectionHint="必选 · 请选择 1 项" />
              <div className="course-type-options upload-course-type-options">
                {COURSE_CATEGORY_OPTIONS.map((option) => (
                  <UploadChoiceCard
                    key={option.value}
                    name="courseCategory"
                    value={option.value}
                    title={option.label}
                    description={option.helper}
                    selected={courseCategory === option.value}
                    onSelect={() => onCourseCategoryChange(option.value)}
                  />
                ))}
              </div>
            </div>
          )}
          {isExperience ? (
            <div className="form-item full">
              <div className="upload-meta-empty">
                <p className="help-text">经验分享标签为系统固定标签，所有分享都会自动附加。</p>
                <p className="help-text">可选择投稿到保研面经、求职面经、考研攻略、留学指南，或填写自定义标签归档到指定栏目。</p>
              </div>
              <div className="form-item full" style={{ marginTop: 12 }}>
                <UploadSectionLabel text="投稿栏目" optional />
                <div className="inline-group wrap">
                  {[
                    ['experience', '经验心得'],
                    ['grad-school', '保研面经'],
                    ['career', '求职面经'],
                    ['postgrad-exam', '考研攻略'],
                    ['overseas', '留学指南'],
                  ].map(([value, label]) => (
                    <label key={value} className={`choice-pill ${experienceTopic === value ? 'active' : ''}`}>
                      <input
                        type="radio"
                        name="experienceTopic"
                        value={value}
                        checked={experienceTopic === value}
                        onChange={() => {
                          onExperienceTopicChange(value as ColumnTopicKey);
                          onExperienceCustomTagChange('');
                        }}
                      />
                      <span>{label}</span>
                    </label>
                  ))}
                  <label className={`choice-pill ${isExperienceCustomTopic ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="experienceTopic"
                      value="custom"
                      checked={isExperienceCustomTopic}
                      onChange={() => onExperienceTopicChange('leetcode')}
                    />
                    <span>自定义标签</span>
                  </label>
                </div>
                {isExperienceCustomTopic && (
                  <div className="form-item full" style={{ marginTop: 10 }}>
                    <input
                      placeholder="填写自定义栏目标签（例如：考研经验 / 竞赛复盘）"
                      value={experienceCustomTag}
                      onChange={(e) => onExperienceCustomTagChange(e.target.value.replace(/\s+/g, ' ').slice(0, 16))}
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
              </div>
              <p className="help-text">
                一键投稿会优先使用“我的”里个人主页概览所填的学校、学院、专业与年级信息；未填写的字段将按默认值补齐。
              </p>
            </div>
          ) : (
            <>
              <div className="form-item">
                <UploadSectionLabel htmlFor="school" text="学校" />
                <select id="school" value={school} onChange={(e) => onSchoolChange(e.target.value)} required>
                  <option value={SUPPORTED_SCHOOL}>{SUPPORTED_SCHOOL}</option>
                </select>
              </div>
              <div className="form-item">
                <UploadSectionLabel htmlFor="college" text="学院" />
                <select
                  id="college"
                  value={college}
                  onChange={(e) => onCollegeChange(e.target.value)}
                  disabled={courseCategory !== 'MAJOR'}
                  required={courseCategory === 'MAJOR'}
                >
                  <option value="">{courseCategory === 'MAJOR' ? '请选择学院' : '无需选择'}</option>
                  {collegeOptions.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-item">
                <UploadSectionLabel text="年级/阶段" />
                <select id="gradeValue" value={gradeValue} onChange={(e) => onGradeValueChange(e.target.value)}>
                  {gradeStageOptions.map((stage) => (
                    <option key={stage} value={stage}>
                      {stage}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-item">
                <UploadSectionLabel text="专业" optional />
                <div className="inline-group wrap">
                  {majorOptions.map((name) => {
                    const checked = selectedMajors.includes(name);
                    return (
                      <label key={name} className={`choice badge-outline ${checked ? 'active' : ''}`}>
                        <input
                          type="checkbox"
                          value={name}
                          checked={checked}
                          disabled={courseCategory !== 'MAJOR'}
                          onChange={(e) => onMajorToggle(name, e.target.checked)}
                        />
                        {name}
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="form-item full">
                <UploadSectionLabel text="标签" optional />
                <div className="inline-group wrap">
                  {presetTags.map((tag) => (
                    <label key={tag} className="choice badge-outline">
                      <input
                        type="checkbox"
                        checked={selectedTags.includes(tag)}
                        disabled={!selectedTags.includes(tag) && tagList.length >= maxTags}
                        onChange={(e) =>
                          onSelectedTagsChange((prev) => {
                            const exists = prev.includes(tag);
                            if (e.target.checked) {
                              if (exists || tagList.length >= maxTags) {
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
                  onChange={(e) => onCustomTagsChange(e.target.value)}
                />
                <p className="help-text">
                  已选择 {tagList.length}/{maxTags} 个标签
                  {trimmedCustom ? '，多余的自定义标签将不会保存' : ''}
                </p>
                <div className="upload-year-field">
                  <UploadSectionLabel text="资料年份" optional />
                  <div className="inline-group wrap">
                    <input
                      type="text"
                      list="year-options"
                      placeholder="可输入或选择：如 2023 / 2023-2024"
                      value={yearTag}
                      onChange={(e) => onYearTagChange(e.target.value)}
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
  );
}
