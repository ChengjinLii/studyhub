import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import ProfileCard from '../../components/ProfileCard';
import ProfilePublications, { type ProfilePublicationsProps } from '../../components/profile/ProfilePublications';

beforeAll(() => { vi.stubGlobal('React', React); });
afterAll(() => { vi.unstubAllGlobals(); });

const uploads = Array.from({ length: 6 }, (_, index) => ({
  materialId: index + 1, title: index === 0 ? '资料 <标题> & 文件' : `资料 ${index}`,
  free: index % 2 === 0, price: index + 0.5, salesCount: 0,
  downloadCount: index, createdAt: `2026-01-0${index + 1}T12:00:00Z`,
}));
const listings = Array.from({ length: 6 }, (_, index) => ({
  itemId: index + 1, title: `好物 ${index}`, price: index + 1,
  wantCount: index, status: 'VISIBLE', createdAt: `2026-01-0${index + 1}T12:00:00Z`,
}));

// Snapshots are recorded from ProfileCard before extracting its presentation.
describe('profile publication rendering', () => {
  it.each([
    { label: 'empty', uploads: [], listings: [] },
    { label: 'single', uploads: uploads.slice(0, 1), listings: listings.slice(0, 1) },
    { label: 'five', uploads: uploads.slice(0, 5), listings: listings.slice(0, 5) },
    { label: 'collapsed six', uploads, listings },
    { label: 'server totals', uploads: [], listings: [], uploadCount: 12, marketCount: 8 },
  ])('preserves $label output', ({ label: _label, ...items }) => {
    const html = renderToStaticMarkup(React.createElement(ProfileCard, {
      profile: { id: 1, username: 'example', nickname: 'Example' },
      ...items,
    }));
    const start = html.indexOf('<div class="profile-card__section"><div class="profile-card__label">我发布的资料');
    expect(start).toBeGreaterThan(-1);
    expect(html.slice(start, html.lastIndexOf('</section>'))).toMatchSnapshot();
  });
});

describe('controlled publication actions', () => {
  const buttonsIn = (node: React.ReactNode): React.ReactElement[] => {
    const result: React.ReactElement[] = [];
    React.Children.forEach(node, (child) => {
      if (!React.isValidElement<{ children?: React.ReactNode }>(child)) return;
      if (child.type === 'button') result.push(child);
      result.push(...buttonsIn(child.props.children));
    });
    return result;
  };

  it.each([
    { expanded: false, loading: false, label: '展开全部' },
    { expanded: false, loading: true, label: '加载中...' },
    { expanded: true, loading: false, label: '收起' },
  ])('keeps parent callbacks and $label state', ({ expanded, loading, label }) => {
    const props: ProfilePublicationsProps = {
      totalUploads: 6, totalListings: 6, visibleUploads: uploads, visibleListings: listings,
      canExpandUploads: true, canExpandListings: true,
      handleExpandUploads: vi.fn(), handleExpandListings: vi.fn(),
      uploadsLoading: loading, listingsLoading: loading,
      uploadsExpanded: expanded, listingsExpanded: expanded,
    };
    const tree = ProfilePublications(props);
    const buttons = buttonsIn(tree);
    expect(buttons).toHaveLength(2);
    expect(buttons[0].props.onClick).toBe(props.handleExpandUploads);
    expect(buttons[1].props.onClick).toBe(props.handleExpandListings);
    for (const button of buttons) {
      expect(button.props.disabled).toBe(loading);
      expect(button.props['data-expanded']).toBe(expanded);
      expect(button.props.children).toBe(label);
    }
  });
});
