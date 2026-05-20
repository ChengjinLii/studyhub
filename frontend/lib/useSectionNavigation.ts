import { useCallback, useEffect, useMemo, useState } from 'react';

type SectionLike = {
  id: string;
};

interface UseSectionNavigationOptions {
  rootMargin?: string;
  threshold?: number[];
}

export const useSectionNavigation = <T extends SectionLike>(
  sections: T[],
  options?: UseSectionNavigationOptions
) => {
  const sectionIds = useMemo(() => sections.map((item) => item.id), [sections]);
  const [activeSection, setActiveSection] = useState(sectionIds[0] || '');

  useEffect(() => {
    if (!sectionIds.length) {
      setActiveSection('');
      return;
    }
    if (!sectionIds.includes(activeSection)) {
      setActiveSection(sectionIds[0]);
    }
  }, [activeSection, sectionIds]);

  useEffect(() => {
    if (typeof window === 'undefined' || !sectionIds.length) return;
    const targets = sectionIds
      .map((id) => document.getElementById(id))
      .filter((item): item is HTMLElement => Boolean(item));
    if (!targets.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
        if (visible.length > 0) {
          setActiveSection(visible[0].target.id);
        }
      },
      {
        rootMargin: options?.rootMargin ?? '-20% 0px -60% 0px',
        threshold: options?.threshold ?? [0.1, 0.35, 0.7],
      }
    );
    targets.forEach((target) => observer.observe(target));
    return () => observer.disconnect();
  }, [options?.rootMargin, options?.threshold, sectionIds]);

  const jumpToSection = useCallback((id: string) => {
    if (typeof window === 'undefined') return;
    const target = document.getElementById(id);
    if (!target) return;
    setActiveSection(id);
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  return {
    activeSection,
    setActiveSection,
    jumpToSection,
  };
};

