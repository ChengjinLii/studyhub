import { fetchAccountProfile, fetchProfile } from './api';
import { getMissingProfileFields } from './profileCompletion';

export const fetchHomeProfileContext = async (token: string, origin?: string) => {
  const [summary, account] = await Promise.all([
    fetchProfile(token, origin).catch((error) => {
      // eslint-disable-next-line no-console
      console.warn('Failed to fetch profile summary', error);
      return null;
    }),
    fetchAccountProfile(token, origin).catch((error) => {
      // eslint-disable-next-line no-console
      console.warn('Failed to fetch account profile completion', error);
      return null;
    }),
  ]);

  return {
    summary,
    missingFields: getMissingProfileFields(account),
  };
};
