import { fetchHomeProfileData } from './api';
import { getMissingProfileFields } from './profileCompletion';

export const fetchHomeProfileContext = async (token: string, origin?: string) => {
  const context = await fetchHomeProfileData(token, origin).catch((error) => {
    // eslint-disable-next-line no-console
    console.warn('Failed to fetch home profile context', error);
    return null;
  });

  return {
    summary: context?.summary ?? null,
    missingFields: getMissingProfileFields(context?.account ?? null),
  };
};
