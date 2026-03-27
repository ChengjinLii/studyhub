export const PRICE_CHOICES = [0, 1, 2, 3, 4, 5] as const;

export const PAYMENT_MEDIA: Record<number, string> = {
  1: '/payments/wechat-1.png',
  2: '/payments/wechat-2.png',
  3: '/payments/wechat-3.png',
  4: '/payments/wechat-4.png',
  5: '/payments/wechat-5.png',
};

export const getPaymentMedia = (price: number) => PAYMENT_MEDIA[Math.round(price)] || null;
