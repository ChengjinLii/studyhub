/* eslint-disable @next/next/no-img-element */
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const SAFE_MARKDOWN_ELEMENTS = [
  'a',
  'blockquote',
  'br',
  'code',
  'del',
  'em',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'hr',
  'img',
  'li',
  'ol',
  'p',
  'pre',
  'strong',
  'table',
  'tbody',
  'td',
  'th',
  'thead',
  'tr',
  'ul',
] as const;

const SAFE_URL_PROTOCOLS = new Set(['http:', 'https:', 'mailto:']);

interface SafeMarkdownProps {
  children: string;
}

export default function SafeMarkdown({ children }: SafeMarkdownProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      allowedElements={[...SAFE_MARKDOWN_ELEMENTS]}
      urlTransform={safeMarkdownUrl}
      components={{
        a: ({ node: _node, href, ...props }) => {
          const safeHref = typeof href === 'string' ? href : '';
          const external = isExternalUrl(safeHref);
          return (
            <a
              {...props}
              href={safeHref || undefined}
              target={external ? '_blank' : undefined}
              rel={external ? 'noopener noreferrer nofollow' : undefined}
            />
          );
        },
        img: ({ node: _node, src, alt, ...props }) => {
          const safeSrc = typeof src === 'string' ? safeMarkdownImageUrl(src) : '';
          if (!safeSrc) return null;
          return (
            <img
              {...props}
              src={safeSrc}
              alt={typeof alt === 'string' ? alt : ''}
              loading="lazy"
              decoding="async"
              referrerPolicy="no-referrer"
            />
          );
        },
      }}
    >
      {children}
    </ReactMarkdown>
  );
}

export function safeMarkdownUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('//')) return '';
  if (trimmed.startsWith('#')) return trimmed;
  if (trimmed.startsWith('/') && !trimmed.startsWith('//')) return trimmed;
  try {
    const url = new URL(trimmed, 'https://studyhub.local');
    return SAFE_URL_PROTOCOLS.has(url.protocol) ? trimmed : '';
  } catch {
    return '';
  }
}

export function safeMarkdownImageUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('//')) return '';
  if (trimmed.startsWith('/') && !trimmed.startsWith('//')) return trimmed;
  return '';
}

function isExternalUrl(value: string) {
  return /^https?:\/\//i.test(value.trim());
}
