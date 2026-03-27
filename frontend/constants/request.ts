export const REQUEST_TIERS = [
  { value: '24H', label: '24小时内交付', ownerMin: 50, followerMin: 30 },
  { value: 'WEEK', label: '1周内交付', ownerMin: 20, followerMin: 15 },
  { value: 'MONTH', label: '1个月内交付', ownerMin: 10, followerMin: 10 },
  { value: 'FLEX', label: '不限', ownerMin: 5, followerMin: 5 },
] as const;

export type RequestTierValue = (typeof REQUEST_TIERS)[number]['value'];

export const getTierLabel = (tier?: string | null) => {
  if (!tier) return '不限';
  const match = REQUEST_TIERS.find((item) => item.value === tier);
  return match?.label ?? '不限';
};
