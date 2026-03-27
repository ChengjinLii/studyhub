export interface SampleMarketItem {
  slug: string;
  title: string;
  price: number;
  category: 'BOOK' | 'DIGITAL' | 'LIFE' | 'SPORT' | 'OTHER';
  thumbnail: string;
  images: string[];
  description: string;
  wantCount: number;
  school?: string;
  sellerName?: string;
  contactType: 'QQ' | 'WECHAT' | 'PHONE';
  contactValue: string;
}

export const SAMPLE_MARKET_ITEMS: SampleMarketItem[] = [
  {
    slug: 'sample-textbook',
    title: '示例教材《通信原理》',
    price: 35,
    category: 'BOOK',
    thumbnail: 'https://placehold.co/600x400?text=Campus+Market+Demo1',
    images: ['https://placehold.co/800x500?text=Campus+Market+Demo1'],
    description: '九成新教材，附赠整理好的笔记，适合准备期末复习的同学。',
    wantCount: 5,
    school: '电子科技大学',
    sellerName: 'Demo 卖家',
    contactType: 'WECHAT',
    contactValue: 'demo_wechat',
  },
  {
    slug: 'sample-storage-box',
    title: '示例日用品「宿舍收纳盒」',
    price: 12,
    category: 'LIFE',
    thumbnail: 'https://placehold.co/600x400?text=Campus+Market+Demo2',
    images: ['https://placehold.co/800x500?text=Campus+Market+Demo2'],
    description: '宿舍桌面收纳盒，轻便耐用，帮助保持整洁。',
    wantCount: 3,
    school: '电子科技大学',
    sellerName: 'Demo 卖家',
    contactType: 'QQ',
    contactValue: '123456789',
  },
];
