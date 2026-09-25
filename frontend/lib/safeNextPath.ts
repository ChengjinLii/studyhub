const FALLBACK_PATH = '/';
const PLACEHOLDER_ORIGIN = 'https://studyhub.invalid';
const UNSAFE_CHARACTERS = /[\u0000-\u001f\u007f\\]/;

const isSingleSlashPath = (value: string) => value.startsWith('/') && !value.startsWith('//');

/**
 * Returns a same-site path that is safe to navigate to after login, or `/` when the
 * candidate could leave the site (protocol-relative, backslash, absolute or scripted URLs).
 */
export function resolveSafeNextPath(value: unknown): string {
  if (typeof value !== 'string' || !isSingleSlashPath(value) || UNSAFE_CHARACTERS.test(value)) {
    return FALLBACK_PATH;
  }
  let url: URL;
  try {
    url = new URL(value, PLACEHOLDER_ORIGIN);
  } catch {
    return FALLBACK_PATH;
  }
  if (url.origin !== PLACEHOLDER_ORIGIN) {
    return FALLBACK_PATH;
  }
  const resolved = `${url.pathname}${url.search}${url.hash}`;
  return isSingleSlashPath(resolved) ? resolved : FALLBACK_PATH;
}
