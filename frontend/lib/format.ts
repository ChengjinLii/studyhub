const LOCALE = 'zh-CN';
const TIME_ZONE = 'Asia/Shanghai';

const buildDateFormatter = (options: Intl.DateTimeFormatOptions) => {
  try {
    return new Intl.DateTimeFormat(LOCALE, { timeZone: TIME_ZONE, ...options });
  } catch (error) {
    return new Intl.DateTimeFormat(LOCALE, options);
  }
};

const numberFormatter = new Intl.NumberFormat(LOCALE);
const dateFormatter = buildDateFormatter({ year: 'numeric', month: '2-digit', day: '2-digit' });
const dateTimeFormatter = buildDateFormatter({
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const toDate = (value?: string | number | Date | null) => {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
};

export const formatNumber = (value?: number | null) => {
  if (value == null || Number.isNaN(value)) return '0';
  return numberFormatter.format(value);
};

export const formatDate = (value?: string | number | Date | null) => {
  const date = toDate(value);
  if (!date) return '';
  return dateFormatter.format(date);
};

export const formatDateTime = (value?: string | number | Date | null) => {
  const date = toDate(value);
  if (!date) return '';
  return dateTimeFormatter.format(date);
};
