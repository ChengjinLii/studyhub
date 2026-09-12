export interface UploadTagsInput {
  selectedTags: string[];
  customTags: string;
  yearTag: string;
  isExperience: boolean;
  resolvedExperienceExtraTag: string | null;
  maxTags: number;
}

export const deriveUploadTags = ({
  selectedTags,
  customTags,
  yearTag,
  isExperience,
  resolvedExperienceExtraTag,
  maxTags,
}: UploadTagsInput): { list: string[]; trimmedCustom: boolean } => {
  if (isExperience) {
    return {
      list: ['经验分享', ...(resolvedExperienceExtraTag ? [resolvedExperienceExtraTag] : [])],
      trimmedCustom: false,
    };
  }
  const trimmedYear = yearTag.trim();
  const baseSet = new Set<string>(selectedTags.filter((tag) => tag !== '经验分享'));
  if (trimmedYear) {
    if (trimmedYear !== '经验分享') {
      baseSet.add(trimmedYear);
    }
  }
  const customEntries = Array.from(
    new Set(
      customTags
        .split(/[,，\s]+/)
        .map((tag) => tag.trim())
        .filter((tag) => tag && tag !== '经验分享')
    )
  );
  const combined: string[] = [];
  Array.from(baseSet).forEach((tag) => {
    if (combined.length < maxTags) combined.push(tag);
  });
  let trimmedCustom = false;
  for (const tag of customEntries) {
    if (combined.length >= maxTags) {
      trimmedCustom = true;
      break;
    }
    if (!combined.includes(tag)) {
      combined.push(tag);
    }
  }
  return {
    list: combined.slice(0, maxTags),
    trimmedCustom,
  };
};
