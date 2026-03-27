import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { FormEvent, useState } from 'react';
import NavBar from '../../components/NavBar';
import { readSession } from '../../lib/auth';
import { marketPath } from '../../lib/slug';
import { SessionUser } from '../../types/user';
import { SUPPORTED_SCHOOL } from '../../constants/metadata';
import { resolveApiBase } from '../../lib/apiBase';

const CATEGORY_OPTIONS = [
  { value: 'BOOK', label: '书籍' },
  { value: 'DIGITAL', label: '数码' },
  { value: 'LIFE', label: '日用品' },
  { value: 'SPORT', label: '运动' },
  { value: 'OTHER', label: '其他' },
];

type ContactType = 'QQ' | 'WECHAT' | 'PHONE';

interface SellPageProps {
  user: SessionUser;
  token: string;
}

export default function SellPage({ user, token }: SellPageProps) {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('BOOK');
  const [description, setDescription] = useState('');
  const [price, setPrice] = useState('10');
  const [school, setSchool] = useState(SUPPORTED_SCHOOL);
  const [contactType, setContactType] = useState<ContactType>('QQ');
  const [contactValue, setContactValue] = useState('');
  const [images, setImages] = useState<File[]>([]);
  const [status, setStatus] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleImageSelection = (files: File[], replace: boolean) => {
    setImages((prev) => {
      const base = replace ? [] : prev;
      return [...base, ...files].slice(0, 3);
    });
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setStatus(null);
    setSubmitting(true);
    try {
      const payload = {
        title,
        category,
        description,
        price: Number(price || '0'),
        contactType,
        contactValue,
        school,
      };
      const formData = new FormData();
      formData.append('payload', new Blob([JSON.stringify(payload)], { type: 'application/json' }));
      images.forEach((file) => formData.append('images', file));
      const apiBase = resolveApiBase(typeof window !== 'undefined' ? window.location.origin : undefined);
      const resp = await fetch(`${apiBase}/market`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok || !json.data) {
        throw new Error(json.msg || '发布失败');
      }
      setStatus({ type: 'success', text: '发布成功，正在跳转…' });
      router.push(marketPath(json.data.id, json.data.title || title));
    } catch (error: any) {
      setStatus({ type: 'error', text: error.message || '发布失败' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container">
        <section className="card upload-card">
          <h2>发布校园集市商品</h2>
          <p className="help-text">填写商品信息，让同校同学更快找到你的好物。</p>
          <form className="form-grid" onSubmit={handleSubmit}>
            <div className="form-item full">
              <label htmlFor="market-title">商品名称</label>
              <input id="market-title" value={title} onChange={(e) => setTitle(e.target.value)} required />
            </div>
            <div className="form-item">
              <label htmlFor="market-category">分类</label>
              <select id="market-category" value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-item">
              <label htmlFor="market-price">价格（元）</label>
              <input
                id="market-price"
                type="number"
                min="0"
                step="0.5"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </div>
            <div className="form-item">
              <label htmlFor="market-school">学校（可选）</label>
              <input
                id="market-school"
                value={school}
                onChange={(e) => setSchool(e.target.value)}
                placeholder="例：电子科技大学"
              />
            </div>
            <div className="form-item full">
              <label htmlFor="market-description">商品描述</label>
              <textarea
                id="market-description"
                rows={4}
                placeholder="简单介绍商品成色、使用情况、交易地点等信息"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className="form-item full">
              <label>上传图片（0-3 张，可选）</label>
              <div className="inline-group wrap">
                <label className="button ghost small" htmlFor="market-image-picker">
                  选择图片
                </label>
                <input
                  id="market-image-picker"
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={(e) => {
                    const files = Array.from(e.target.files || []);
                    handleImageSelection(files, true);
                    e.currentTarget.value = '';
                  }}
                  style={{ display: 'none' }}
                />
                <label className="button ghost small" htmlFor="market-image-camera">
                  打开相机
                </label>
                <input
                  id="market-image-camera"
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={(e) => {
                    const files = Array.from(e.target.files || []);
                    handleImageSelection(files, false);
                    e.currentTarget.value = '';
                  }}
                  style={{ display: 'none' }}
                />
              </div>
              {images.length > 0 && (
                <p className="help-text">已选择 {images.length} 张，还可添加 {Math.max(0, 3 - images.length)} 张。</p>
              )}
              {images.length === 0 && <p className="help-text">可不上传图片，最多上传 3 张。</p>}
            </div>
            <div className="form-item">
              <label>联系方式</label>
              <div className="inline-group wrap">
                {(['QQ', 'WECHAT', 'PHONE'] as ContactType[]).map((type) => (
                  <label key={type} className="choice">
                    <input
                      type="radio"
                      name="contactType"
                      value={type}
                      checked={contactType === type}
                      onChange={(e) => setContactType(e.target.value as ContactType)}
                    />
                    {type === 'QQ' && 'QQ'}
                    {type === 'WECHAT' && '微信'}
                    {type === 'PHONE' && '手机号'}
                  </label>
                ))}
              </div>
              <input
                placeholder="请填写对应联系方式"
                value={contactValue}
                onChange={(e) => setContactValue(e.target.value)}
                required
              />
            </div>
            <div className="form-item">
              <button className="button primary" type="submit" disabled={submitting}>
                {submitting ? '发布中...' : '提交商品'}
              </button>
              <Link className="button ghost" href="/market">
                返回集市
              </Link>
            </div>
            {status && <p className={status.type === 'error' ? 'error-text' : 'success-text'}>{status.text}</p>}
          </form>
        </section>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<SellPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  if (!session.user) {
    return {
      redirect: {
        destination: `/login?next=${encodeURIComponent('/market/sell')}`,
        permanent: false,
      },
    };
  }
  return {
    props: {
      user: session.user,
      token: session.token || '',
    },
  };
};
