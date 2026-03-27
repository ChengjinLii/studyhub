const normalizeApiBase = (base?: string) => {
  if (!base) return 'http://127.0.0.1:8111/api';
  const trimmed = base.replace(/\/+$/, '');
  if (/\/api$/i.test(trimmed)) {
    return trimmed;
  }
  return `${trimmed}/api`;
};

export const getServerApiBase = () => {
  const base = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE;
  return normalizeApiBase(base);
};
