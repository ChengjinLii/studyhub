import Link from 'next/link';
import { useEffect, useMemo, useRef, useState } from 'react';
import AppImage from './AppImage';
import SafeMarkdown from './SafeMarkdown';
import { toErrorMessage } from '../lib/errors';
import { formatDate } from '../lib/format';
import {
  clearPayoutQr,
  fetchUserMarketListings,
  fetchUserUploads,
  updateAccountProfile,
  uploadPayoutQr,
} from '../lib/profileApi';
import { marketPath, materialPath, userPath } from '../lib/slug';
import { UploadItem, MarketListingItem } from '../types/profile';
import { PublicUserProfile, UserAccountProfile, UserFollowItem } from '../types/userProfile';
import { SUPPORTED_SCHOOL, SUPPORTED_COLLEGES, SUPPORTED_MAJORS, GRADE_STAGE_OPTIONS } from '../constants/metadata';

type ProfileBase = Pick<
  UserAccountProfile,
  | 'id'
  | 'username'
  | 'nickname'
  | 'email'
  | 'emailPrivacy'
  | 'avatar'
  | 'signature'
  | 'school'
  | 'college'
  | 'major'
  | 'gradeStages'
  | 'purchaseCount'
  | 'saleCount'
  | 'legendaryContributorUntil'
  | 'payoutQrUrl'
> &
  Partial<Pick<PublicUserProfile, 'emailVisible'>>;

interface ProfileCardProps {
  profile: ProfileBase;
  uploads: UploadItem[];
  listings: MarketListingItem[];
  uploadCount?: number;
  marketCount?: number;
  editable?: boolean;
  followingUsers?: UserFollowItem[];
  followersUsers?: UserFollowItem[];
  followTab?: 'following' | 'followers';
  followLoading?: boolean;
  followMessage?: { type: 'success' | 'error'; message: string } | null;
  onFollowTabChange?: (tab: 'following' | 'followers') => void;
  onProfileUpdated?: (next: UserAccountProfile) => void;
}

const formatMarkdown = (value: string) => value.replace(/\r?\n/g, '  \n');

export default function ProfileCard({
  profile,
  uploads,
  listings,
  uploadCount,
  marketCount,
  editable,
  followingUsers,
  followersUsers,
  followTab,
  followLoading,
  followMessage,
  onFollowTabChange,
  onProfileUpdated,
}: ProfileCardProps) {
  const [nickname, setNickname] = useState(profile.nickname || profile.username);
  const [emailPrivacy, setEmailPrivacy] = useState(Boolean(profile.emailPrivacy));
  const [signature, setSignature] = useState(profile.signature ?? '');
  const [school, setSchool] = useState(profile.school ?? '');
  const [college, setCollege] = useState(profile.college ?? '');
  const [major, setMajor] = useState(profile.major ?? '');
  const [gradeStages, setGradeStages] = useState<string[]>(
    Array.isArray(profile.gradeStages) ? profile.gradeStages : []
  );
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [payoutQrUrl, setPayoutQrUrl] = useState(profile.payoutQrUrl ?? null);
  const [uploadingPayoutQr, setUploadingPayoutQr] = useState(false);
  const [dragOverPayoutQr, setDragOverPayoutQr] = useState(false);
  const [editingNickname, setEditingNickname] = useState(false);
  const [editingSignature, setEditingSignature] = useState(false);
  const [editingSchool, setEditingSchool] = useState(false);
  const nicknameInputRef = useRef<HTMLInputElement | null>(null);
  const payoutQrInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadsState, setUploadsState] = useState<UploadItem[]>(uploads);
  const [listingsState, setListingsState] = useState<MarketListingItem[]>(listings);
  const [uploadsExpanded, setUploadsExpanded] = useState(false);
  const [listingsExpanded, setListingsExpanded] = useState(false);
  const [followExpanded, setFollowExpanded] = useState(false);
  const [uploadsLoading, setUploadsLoading] = useState(false);
  const [listingsLoading, setListingsLoading] = useState(false);
  const [localFollowTab, setLocalFollowTab] = useState<'following' | 'followers'>('following');

  useEffect(() => {
    setNickname(profile.nickname || profile.username);
    setEmailPrivacy(Boolean(profile.emailPrivacy));
    setSignature(profile.signature ?? '');
    setSchool(profile.school ?? '');
    setCollege(profile.college ?? '');
    setMajor(profile.major ?? '');
    setGradeStages(Array.isArray(profile.gradeStages) ? profile.gradeStages : []);
    setPayoutQrUrl(profile.payoutQrUrl ?? null);
    setEditingNickname(false);
    setEditingSignature(false);
    setEditingSchool(false);
  }, [profile]);

  useEffect(() => {
    setUploadsState(uploads);
  }, [uploads]);

  useEffect(() => {
    setListingsState(listings);
  }, [listings]);

  useEffect(() => {
    if (editingNickname) {
      nicknameInputRef.current?.focus();
    }
  }, [editingNickname]);

  const displayName = useMemo(() => {
    const trimmed = nickname?.trim();
    return trimmed || profile.username || 'StudyHub 用户';
  }, [nickname, profile.username]);

  const resetSignatureEdit = () => {
    setSignature(profile.signature ?? '');
    setEditingSignature(false);
    setMessage(null);
  };

  const resetNicknameEdit = () => {
    setNickname(profile.nickname || profile.username);
    setEditingNickname(false);
    setMessage(null);
  };

  const toggleSignatureEdit = () => {
    if (editingSignature) {
      resetSignatureEdit();
      return;
    }
    setMessage(null);
    setEditingSignature(true);
  };

  const toggleNicknameEdit = () => {
    if (editingNickname) {
      resetNicknameEdit();
      return;
    }
    setMessage(null);
    setEditingNickname(true);
  };

  const resetSchoolEdit = () => {
    setSchool(profile.school ?? '');
    setCollege(profile.college ?? '');
    setMajor(profile.major ?? '');
    setGradeStages(Array.isArray(profile.gradeStages) ? profile.gradeStages : []);
    setEditingSchool(false);
    setMessage(null);
  };

  const legendaryActive = useMemo(() => {
    if (!profile.legendaryContributorUntil) return false;
    const ts = Date.parse(profile.legendaryContributorUntil);
    return Number.isFinite(ts) && ts > Date.now();
  }, [profile.legendaryContributorUntil]);

  const avatarText = useMemo(() => displayName.slice(0, 1).toUpperCase(), [displayName]);
  const totalUploads = uploadCount ?? uploadsState.length;
  const totalListings = marketCount ?? listingsState.length;
  const purchaseCount = profile.purchaseCount ?? 0;
  const saleCount = profile.saleCount ?? 0;
  const followingCount = followingUsers?.length ?? 0;
  const followersCount = followersUsers?.length ?? 0;
  const sortedUploads = useMemo(() => {
    return [...uploadsState].sort((a, b) => {
      const countDiff = (b.downloadCount ?? 0) - (a.downloadCount ?? 0);
      if (countDiff !== 0) return countDiff;
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    });
  }, [uploadsState]);
  const sortedListings = useMemo(() => {
    return [...listingsState].sort((a, b) => {
      const countDiff = (b.wantCount ?? 0) - (a.wantCount ?? 0);
      if (countDiff !== 0) return countDiff;
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    });
  }, [listingsState]);
  const visibleUploads = uploadsExpanded ? sortedUploads : sortedUploads.slice(0, 5);
  const visibleListings = listingsExpanded ? sortedListings : sortedListings.slice(0, 5);
  const canExpandUploads = totalUploads > 5;
  const canExpandListings = totalListings > 5;

  const showEmail = editable
    ? profile.email
    : profile.emailVisible === false
      ? null
      : profile.email;
  const signatureDisplay = editable ? signature : (profile.signature ?? '').trim();
  const signatureMarkdown = signatureDisplay ? formatMarkdown(signatureDisplay) : '';
  const signatureCount = signature.length;
  const schoolDisplay = (editable ? school : profile.school ?? '').trim();
  const collegeDisplay = (editable ? college : profile.college ?? '').trim();
  const majorDisplay = (editable ? major : profile.major ?? '').trim();
  const hasSchool = Boolean(schoolDisplay);
  const gradeStagesDisplay = (editable ? gradeStages : profile.gradeStages ?? []).filter(Boolean);
  const hasFollowSection = Boolean(followingUsers || followersUsers);
  const showFollowStats = editable || hasFollowSection;
  const activeFollowTab = followTab ?? localFollowTab;
  const setActiveFollowTab = onFollowTabChange ?? setLocalFollowTab;
  const followItems =
    activeFollowTab === 'followers' ? followersUsers ?? [] : followingUsers ?? [];
  const visibleFollowItems = followExpanded ? followItems : followItems.slice(0, 5);
  const canExpandFollows = followItems.length > 5;
  const followEmptyText =
    activeFollowTab === 'followers' ? '暂时还没有粉丝，先发布点资料吧。' : '还没有关注的人，去首页看看吧。';

  useEffect(() => {
    setFollowExpanded(false);
  }, [activeFollowTab]);

  const handleSave = async () => {
    if (!editable) return;
    setMessage(null);
    setSaving(true);
    try {
      const nextProfile = await updateAccountProfile({
        nickname: nickname?.trim(),
        emailPrivacy,
        signature: signature.trim(),
        school: school.trim(),
        college: college.trim(),
        major: major.trim(),
        gradeStages,
      });
      onProfileUpdated?.(nextProfile);
      setEditingNickname(false);
      setEditingSignature(false);
      setEditingSchool(false);
      setMessage({ type: 'success', text: '已保存' });
    } catch (error: unknown) {
      setMessage({ type: 'error', text: toErrorMessage(error, '更新失败') });
    } finally {
      setSaving(false);
    }
  };

  const handleSchoolChange = (value: string) => {
    setSchool(value);
    if (!value) {
      setCollege('');
      setMajor('');
    }
  };

  const handleExpandUploads = async () => {
    if (!uploadsExpanded && profile.id && uploadsState.length < totalUploads) {
      setUploadsLoading(true);
      try {
        setUploadsState(await fetchUserUploads(profile.id));
      } finally {
        setUploadsLoading(false);
      }
    }
    setUploadsExpanded((prev) => !prev);
  };

  const handleExpandListings = async () => {
    if (!listingsExpanded && profile.id && listingsState.length < totalListings) {
      setListingsLoading(true);
      try {
        setListingsState(await fetchUserMarketListings(profile.id));
      } finally {
        setListingsLoading(false);
      }
    }
    setListingsExpanded((prev) => !prev);
  };

  const handleUploadPayoutQr = async (file?: File | null) => {
    if (!editable || !file) return;
    if (!file.type.startsWith('image/')) {
      setMessage({ type: 'error', text: '仅支持上传图片文件' });
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setMessage({ type: 'error', text: '收款码图片不能超过 5MB' });
      return;
    }
    setMessage(null);
    setUploadingPayoutQr(true);
    try {
      const nextProfile = await uploadPayoutQr(file);
      setPayoutQrUrl(nextProfile.payoutQrUrl ?? null);
      onProfileUpdated?.(nextProfile);
      setMessage({ type: 'success', text: '收款码已更新' });
    } catch (error: unknown) {
      setMessage({ type: 'error', text: toErrorMessage(error, '上传失败') });
    } finally {
      setUploadingPayoutQr(false);
      if (payoutQrInputRef.current) {
        payoutQrInputRef.current.value = '';
      }
    }
  };

  const handleClearPayoutQr = async () => {
    if (!editable) return;
    setMessage(null);
    setUploadingPayoutQr(true);
    try {
      const nextProfile = await clearPayoutQr();
      setPayoutQrUrl(nextProfile.payoutQrUrl ?? null);
      onProfileUpdated?.(nextProfile);
      setMessage({ type: 'success', text: '收款码已删除' });
    } catch (error: unknown) {
      setMessage({ type: 'error', text: toErrorMessage(error, '删除失败') });
    } finally {
      setUploadingPayoutQr(false);
    }
  };

  const renderFollowList = () => {
    if (followLoading) {
      return <p className="help-text">加载中...</p>;
    }
    if (followItems.length === 0) {
      return <p className="help-text">{followEmptyText}</p>;
    }
    return (
      <ul className="follow-list">
        {visibleFollowItems.map((item) => {
          const displayName = (item.nickname || item.username || '').trim() || 'StudyHub 用户';
          const avatarInitial = displayName.slice(0, 1).toUpperCase();
          const signatureValue = item.signature?.trim();
          const signatureMarkdown = signatureValue ? formatMarkdown(signatureValue) : '';
          const schoolParts = [item.school, item.college, item.major].filter(Boolean);
          const schoolText = schoolParts.length > 0 ? schoolParts.join(' · ') : '未填写学校信息';
          return (
            <li key={`follow-${item.id}`} className="follow-list__item">
              <div className="follow-list__avatar" aria-hidden="true">
                {avatarInitial}
              </div>
              <div className="follow-list__meta">
                <div className="follow-list__name">
                  {displayName}
                  <span className="follow-list__handle">@{item.username}</span>
                </div>
                <div className="follow-list__school">{schoolText}</div>
                {signatureValue ? (
                  <div className="follow-list__signature profile-markdown">
                    <SafeMarkdown>{signatureMarkdown}</SafeMarkdown>
                  </div>
                ) : (
                  <div className="follow-list__signature follow-list__muted">这个人还没有签名。</div>
                )}
              </div>
              <Link className="button ghost small" href={userPath(item.id, displayName)}>
                查看主页
              </Link>
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <section className="card profile-card">
      <div className="profile-card__hero">
        <div className="profile-card__header">
          <div className="profile-card__avatar" aria-hidden="true">
            {avatarText}
          </div>
          <div className="profile-card__title">
            <div className="profile-card__name-line">
              <div className="profile-card__name">{displayName}</div>
              {legendaryActive && <span className="legendary-badge">传奇贡献者</span>}
            </div>
            <div className="profile-card__meta">@{profile.username}</div>
          </div>
        </div>
      <div className="profile-card__stats">
        <div className="profile-card__stat">
          <span className="profile-card__stat-value">{totalUploads}</span>
          <span className="profile-card__stat-label">资料</span>
        </div>
        <div className="profile-card__stat">
          <span className="profile-card__stat-value">{totalListings}</span>
          <span className="profile-card__stat-label">好物</span>
        </div>
        <div className="profile-card__stat">
          <span className="profile-card__stat-value">{purchaseCount}</span>
          <span className="profile-card__stat-label">购买</span>
        </div>
        <div className="profile-card__stat">
          <span className="profile-card__stat-value">{saleCount}</span>
          <span className="profile-card__stat-label">售出</span>
        </div>
        {showFollowStats && (
          <>
            <div className="profile-card__stat">
              <span className="profile-card__stat-value">{followersCount}</span>
              <span className="profile-card__stat-label">粉丝</span>
            </div>
            <div className="profile-card__stat">
              <span className="profile-card__stat-value">{followingCount}</span>
              <span className="profile-card__stat-label">关注</span>
            </div>
          </>
        )}
      </div>
    </div>

    <div className="profile-card__section profile-card__section--signature">
      <div className="profile-card__label-row">
        <div className="profile-card__label">个性签名</div>
        {editable && (
          <button
            type="button"
            className={`profile-card__edit profile-card__edit--text${editingSignature ? ' is-active' : ''}`}
            onClick={toggleSignatureEdit}
            disabled={saving}
            aria-label={editingSignature ? '取消编辑签名' : '编辑签名'}
            aria-pressed={editingSignature}
            title={editingSignature ? '取消编辑签名' : '编辑签名'}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M4 15.5V20h4.5L19 9.5 14.5 5 4 15.5z"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <path d="M13 6.5l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
            </svg>
            <span>{editingSignature ? '取消编辑' : '编辑签名'}</span>
          </button>
        )}
      </div>
      <div className="profile-card__signature-hint">展示在个人主页，支持 Markdown，最多 300 字。</div>
      {editable && editingSignature ? (
        <div className="profile-card__signature-editor">
          <textarea
            className="profile-card__textarea profile-card__textarea--signature"
            value={signature}
            onChange={(e) => setSignature(e.target.value)}
              maxLength={300}
              rows={4}
              placeholder="写点让别人记住你的话（支持 Markdown，300 字以内）"
            />
          <div className="profile-card__signature-footer">
              <div className="profile-card__signature-tags">
                <span className="profile-card__signature-tag">Markdown</span>
                <span className="profile-card__signature-tag profile-card__signature-tag--muted">300 字以内</span>
              </div>
              <span>{signatureCount}/300</span>
          </div>
          <div className="profile-card__section-actions">
            <span className="profile-card__edit-status">编辑中</span>
            <button className="button primary profile-card__save-inline" type="button" onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
            <button className="button ghost profile-card__cancel-inline" type="button" onClick={resetSignatureEdit} disabled={saving}>
              取消修改
            </button>
            {message && (
              <span className={message.type === 'error' ? 'error-text' : 'success-text'}>{message.text}</span>
            )}
          </div>
        </div>
      ) : signatureDisplay ? (
        <div className="profile-card__signature-preview profile-markdown">
          <SafeMarkdown>{signatureMarkdown}</SafeMarkdown>
        </div>
      ) : (
        <div className="profile-card__signature-empty">这个人还没有写签名。</div>
      )}
      </div>

      <div className="profile-card__section">
        <div className="profile-card__label-row">
          <div className="profile-card__label">昵称</div>
          {editable && (
            <button
              type="button"
              className={`profile-card__edit profile-card__edit--text${editingNickname ? ' is-active' : ''}`}
              onClick={toggleNicknameEdit}
              disabled={saving}
              aria-label={editingNickname ? '取消修改昵称' : '修改昵称'}
              aria-pressed={editingNickname}
              title={editingNickname ? '取消修改昵称' : '修改昵称'}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M4 15.5V20h4.5L19 9.5 14.5 5 4 15.5z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinejoin="round"
                />
                <path d="M13 6.5l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
              </svg>
              <span>{editingNickname ? '取消修改' : '修改'}</span>
            </button>
          )}
        </div>
        {editable && (
          <div className="profile-card__identity-hint">昵称用于公开展示，用户名用于登录且保持唯一，二者可以不同。</div>
        )}
        {editable ? (
          editingNickname ? (
            <>
              <input
                ref={nicknameInputRef}
                className="profile-card__input"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                maxLength={24}
                placeholder="设置一个展示昵称"
              />
              <div className="profile-card__section-actions">
                <span className="profile-card__edit-status">编辑中</span>
                <button className="button primary profile-card__save-inline" type="button" onClick={handleSave} disabled={saving}>
                  {saving ? '保存中...' : '保存'}
                </button>
                <button className="button ghost profile-card__cancel-inline" type="button" onClick={resetNicknameEdit} disabled={saving}>
                  取消修改
                </button>
                {message && (
                  <span className={message.type === 'error' ? 'error-text' : 'success-text'}>{message.text}</span>
                )}
              </div>
            </>
          ) : (
            <div className="profile-card__value">{displayName}</div>
          )
        ) : (
          <div className="profile-card__value">{displayName}</div>
        )}
      </div>

      <div className="profile-card__section">
        <div className="profile-card__label-row">
          <div className="profile-card__label">学校信息</div>
          {editable && (
            <button
              type="button"
              className="profile-card__edit profile-card__edit--text"
              onClick={() => setEditingSchool(true)}
              disabled={editingSchool}
              aria-label="编辑学校信息"
              title="编辑学校信息"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M4 15.5V20h4.5L19 9.5 14.5 5 4 15.5z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinejoin="round"
                />
                <path d="M13 6.5l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
              </svg>
              <span>修改</span>
            </button>
          )}
        </div>
        <div className="profile-card__field-grid">
          <div className="profile-card__field">
            <label className="profile-card__field-label" htmlFor="profile-school">
              学校
            </label>
            {editable && editingSchool ? (
              <div className="profile-card__select-wrap">
                <select
                  id="profile-school"
                  className="profile-card__input profile-card__input--select"
                  value={school}
                  onChange={(e) => handleSchoolChange(e.target.value)}
                >
                  <option value="">未填写</option>
                  <option value={SUPPORTED_SCHOOL}>{SUPPORTED_SCHOOL}</option>
                </select>
                <span className="profile-card__select-indicator" aria-hidden="true">
                  <svg viewBox="0 0 24 24">
                    <path
                      d="M6 9l6 6 6-6"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
              </div>
            ) : (
              <div className={`profile-card__value profile-card__info-value ${schoolDisplay ? '' : 'muted'}`}>
                {schoolDisplay || '未填写'}
              </div>
            )}
          </div>
          <div className="profile-card__field">
            <label className="profile-card__field-label" htmlFor="profile-college">
              学院
            </label>
            {editable && editingSchool ? (
              <div className="profile-card__select-wrap">
                <select
                  id="profile-college"
                  className="profile-card__input profile-card__input--select"
                  value={college}
                  onChange={(e) => setCollege(e.target.value)}
                  disabled={!hasSchool}
                >
                  <option value="">未填写</option>
                  {SUPPORTED_COLLEGES.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <span className="profile-card__select-indicator" aria-hidden="true">
                  <svg viewBox="0 0 24 24">
                    <path
                      d="M6 9l6 6 6-6"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
              </div>
            ) : (
              <div className={`profile-card__value profile-card__info-value ${collegeDisplay ? '' : 'muted'}`}>
                {collegeDisplay || '未填写'}
              </div>
            )}
          </div>
          <div className="profile-card__field profile-card__field--wide">
            <label className="profile-card__field-label" htmlFor="profile-major">
              专业
            </label>
            {editable && editingSchool ? (
              <div className="profile-card__select-wrap">
                <select
                  id="profile-major"
                  className="profile-card__input profile-card__input--select"
                  value={major}
                  onChange={(e) => setMajor(e.target.value)}
                  disabled={!hasSchool}
                >
                  <option value="">未填写</option>
                  {SUPPORTED_MAJORS.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <span className="profile-card__select-indicator" aria-hidden="true">
                  <svg viewBox="0 0 24 24">
                    <path
                      d="M6 9l6 6 6-6"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
              </div>
            ) : (
              <div className={`profile-card__value profile-card__info-value ${majorDisplay ? '' : 'muted'}`}>
                {majorDisplay || '未填写'}
              </div>
            )}
          </div>
          <div className="profile-card__field profile-card__field--wide">
            <label className="profile-card__field-label">年级/阶段</label>
            {editable && editingSchool ? (
              <>
                <div className="profile-card__grade-options">
                  {GRADE_STAGE_OPTIONS.map((stage) => {
                    const checked = gradeStages.includes(stage);
                    return (
                      <label
                        key={stage}
                        className={`choice-pill profile-card__grade-choice ${checked ? 'active' : ''}`}
                      >
                        <input
                          type="checkbox"
                          value={stage}
                          checked={checked}
                          onChange={() => {
                            setGradeStages((prev) => {
                              const next = prev.includes(stage)
                                ? prev.filter((value) => value !== stage)
                                : [...prev, stage];
                              return GRADE_STAGE_OPTIONS.filter((option) => next.includes(option));
                            });
                          }}
                        />
                        {stage}
                      </label>
                    );
                  })}
                </div>
                <div className="profile-card__grade-preview">
                  <span className="profile-card__grade-preview-label">已选择</span>
                  {gradeStagesDisplay.length > 0 ? (
                    <div className="profile-card__grade-tags">
                      {gradeStagesDisplay.map((stage) => (
                        <span key={stage} className="profile-card__grade-pill">
                          {stage}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="profile-card__value muted">未选择</span>
                  )}
                </div>
              </>
            ) : gradeStagesDisplay.length > 0 ? (
              <div className="profile-card__grade-tags">
                {gradeStagesDisplay.map((stage) => (
                  <span key={stage} className="profile-card__grade-pill">
                    {stage}
                  </span>
                ))}
              </div>
            ) : (
              <div className="profile-card__value profile-card__info-value muted">未填写</div>
            )}
          </div>
        </div>
        {editable && editingSchool && (
          <div className="profile-card__section-actions">
            <span className="profile-card__edit-status">编辑中</span>
            <button className="button primary profile-card__save-inline" type="button" onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
            <button className="button ghost profile-card__cancel-inline" type="button" onClick={resetSchoolEdit} disabled={saving}>
              取消修改
            </button>
            {message && (
              <span className={message.type === 'error' ? 'error-text' : 'success-text'}>{message.text}</span>
            )}
          </div>
        )}
      </div>

      <div className="profile-card__section">
        <div className="profile-card__label">绑定邮箱</div>
        {showEmail ? (
          <div className="profile-card__value">{showEmail}</div>
        ) : (
          <div className="profile-card__value muted">已隐藏</div>
        )}
        {editable && (
          <label className="profile-card__toggle">
            <input
              type="checkbox"
              checked={emailPrivacy}
              onChange={(e) => setEmailPrivacy(e.target.checked)}
            />
            <span>对外隐藏邮箱</span>
          </label>
        )}
        {(editable || payoutQrUrl) && (
          <div className="profile-card__payout-block" id="payout-qr">
            <div className="profile-card__payout-label">个人收款码</div>
            <div className="profile-card__payout-hint">用于创作者收益结算，仅本人和负责结算的授权管理员可见。</div>
            {editable && (
              <>
                <input
                  ref={payoutQrInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="profile-card__payout-file-input"
                  onChange={(e) => handleUploadPayoutQr(e.target.files?.[0] ?? null)}
                />
                <div
                  className={`profile-card__payout-dropzone ${dragOverPayoutQr ? 'is-dragover' : ''} ${payoutQrUrl ? 'has-preview' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOverPayoutQr(true);
                  }}
                  onDragLeave={() => setDragOverPayoutQr(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragOverPayoutQr(false);
                    handleUploadPayoutQr(e.dataTransfer.files?.[0] ?? null);
                  }}
                  onClick={() => {
                    if (!payoutQrUrl && !uploadingPayoutQr) {
                      payoutQrInputRef.current?.click();
                    }
                  }}
                  onKeyDown={(event) => {
                    if (!payoutQrUrl && !uploadingPayoutQr && (event.key === 'Enter' || event.key === ' ')) {
                      event.preventDefault();
                      payoutQrInputRef.current?.click();
                    }
                  }}
                  role={!payoutQrUrl ? 'button' : undefined}
                  tabIndex={!payoutQrUrl ? 0 : undefined}
                >
                  {payoutQrUrl ? (
                    <>
                      <a
                        href={payoutQrUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="profile-card__payout-preview-link"
                        title="点击查看大图"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <AppImage className="profile-card__payout-preview" src={payoutQrUrl} alt="个人收款码" loading="lazy" />
                      </a>
                      <div className="profile-card__payout-actions">
                      <button
                        className="button ghost small"
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          handleClearPayoutQr();
                        }}
                        disabled={uploadingPayoutQr}
                      >
                        删除
                      </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="profile-card__payout-drop-title">
                        {uploadingPayoutQr ? '上传中...' : '拖拽收款码到这里，或点击选择图片'}
                      </div>
                      <div className="profile-card__payout-drop-subtitle">支持 PNG/JPG/WEBP，最大 5MB</div>
                    </>
                  )}
                </div>
              </>
            )}
            {!editable && payoutQrUrl ? (
              <a
                href={payoutQrUrl}
                target="_blank"
                rel="noreferrer"
                className="profile-card__payout-preview-link"
                title="点击查看大图"
              >
                <AppImage className="profile-card__payout-preview" src={payoutQrUrl} alt="个人收款码" loading="lazy" />
              </a>
            ) : !payoutQrUrl ? (
              <div className="profile-card__payout-empty">尚未上传收款码</div>
            ) : null}
          </div>
        )}
      </div>

      {hasFollowSection && (
        <div className="profile-card__section profile-card__section--follow">
          <div className="profile-card__label">关注与粉丝</div>
          <div className="profile-tabs follow-tabs">
            <button
              type="button"
              className={`profile-tab ${activeFollowTab === 'following' ? 'active' : ''}`}
              onClick={() => setActiveFollowTab('following')}
            >
              关注 {followingUsers?.length ?? 0}
            </button>
            <button
              type="button"
              className={`profile-tab ${activeFollowTab === 'followers' ? 'active' : ''}`}
              onClick={() => setActiveFollowTab('followers')}
            >
              粉丝 {followersUsers?.length ?? 0}
            </button>
          </div>
          {followMessage && (
            <p className={followMessage.type === 'error' ? 'error-text' : 'success-text'}>
              {followMessage.message}
            </p>
          )}
          {renderFollowList()}
          {canExpandFollows && (
            <button
              type="button"
              className="profile-card__expand"
              onClick={() => setFollowExpanded((prev) => !prev)}
              data-expanded={followExpanded}
            >
              {followExpanded ? '收起' : '展开全部'}
            </button>
          )}
        </div>
      )}

      <div className="profile-card__section">
        <div className="profile-card__label">我发布的资料</div>
        <div className="profile-card__count">{totalUploads} 条</div>
        {visibleUploads.length === 0 ? (
          <div className="profile-card__empty">暂无发布</div>
        ) : (
          <ul className="profile-card__list">
            {visibleUploads.map((item) => (
              <li key={item.materialId}>
                <div className="profile-card__list-main">
                  <Link href={materialPath(item.materialId, item.title)}>{item.title}</Link>
                  <span className="profile-card__hint">
                    下载 {item.downloadCount ?? 0} · {formatDate(item.createdAt)}
                  </span>
                </div>
                <span className="profile-card__badge">
                  {item.free ? '免费' : `¥${item.price.toFixed(2)}`}
                </span>
              </li>
            ))}
          </ul>
        )}
        {canExpandUploads && (
          <button
            type="button"
            className="profile-card__expand"
            onClick={handleExpandUploads}
            disabled={uploadsLoading}
            data-expanded={uploadsExpanded}
          >
            {uploadsExpanded ? '收起' : uploadsLoading ? '加载中...' : '展开全部'}
          </button>
        )}
      </div>

      <div className="profile-card__section">
        <div className="profile-card__label">我发布的好物</div>
        <div className="profile-card__count">{totalListings} 条</div>
        {visibleListings.length === 0 ? (
          <div className="profile-card__empty">暂无发布</div>
        ) : (
          <ul className="profile-card__list">
            {visibleListings.map((item) => (
              <li key={item.itemId}>
                <div className="profile-card__list-main">
                  <Link href={marketPath(item.itemId, item.title)}>{item.title}</Link>
                  <span className="profile-card__hint">
                    想要 {item.wantCount ?? 0} · {formatDate(item.createdAt)}
                  </span>
                </div>
                <span className="profile-card__badge">¥{item.price.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        )}
        {canExpandListings && (
          <button
            type="button"
            className="profile-card__expand"
            onClick={handleExpandListings}
            disabled={listingsLoading}
            data-expanded={listingsExpanded}
          >
            {listingsExpanded ? '收起' : listingsLoading ? '加载中...' : '展开全部'}
          </button>
        )}
      </div>
    </section>
  );
}
