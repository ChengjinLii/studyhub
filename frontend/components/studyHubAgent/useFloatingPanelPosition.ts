import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react';
import { FloatingWidgetPosition } from './types';

interface UseFloatingPanelPositionOptions {
  storageKey: string;
  closedWidth: number;
  closedHeight: number;
}

type DragState = {
  pointerId: number;
  offsetX: number;
  offsetY: number;
  dragging: boolean;
  startX: number;
  startY: number;
  source: 'launcher' | 'header';
  restorePosition: FloatingWidgetPosition | null;
  viewportOffsetX: number;
  viewportOffsetY: number;
};

export const useFloatingPanelPosition = ({
  storageKey,
  closedWidth,
  closedHeight,
}: UseFloatingPanelPositionOptions) => {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<FloatingWidgetPosition | null>(null);
  const widgetRef = useRef<HTMLElement>(null);
  const launcherPositionRef = useRef<FloatingWidgetPosition | null>(null);
  const dragRef = useRef<DragState | null>(null);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (typeof parsed?.left === 'number' && typeof parsed?.top === 'number') {
        setPosition(constrainPosition(parsed.left, parsed.top, closedWidth, closedHeight));
      }
    } catch {
      // ignore invalid local state
    }
  }, [closedHeight, closedWidth, storageKey]);

  useEffect(() => {
    if (!position) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(position));
    } catch {
      // ignore storage errors
    }
  }, [position, storageKey]);

  const constrainCurrentPosition = useCallback(() => {
    if (!position || !widgetRef.current) return;
    const rect = widgetRef.current.getBoundingClientRect();
    const nextPosition = constrainPosition(position.left, position.top, rect.width, rect.height);
    if (nextPosition.left !== position.left || nextPosition.top !== position.top) {
      setPosition(nextPosition);
    }
  }, [position]);

  useEffect(() => {
    constrainCurrentPosition();
  }, [constrainCurrentPosition, open]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const onResize = () => constrainCurrentPosition();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [constrainCurrentPosition]);

  const widgetStyle = useMemo<CSSProperties | undefined>(() => {
    if (!position) return undefined;
    return {
      left: `${position.left}px`,
      top: `${position.top}px`,
      right: 'auto',
      bottom: 'auto',
    };
  }, [position]);

  const startDrag = useCallback((event: ReactPointerEvent<HTMLElement>, source: 'launcher' | 'header') => {
    if (event.button !== 0 || !widgetRef.current) return;
    const widgetRect = widgetRef.current.getBoundingClientRect();
    const handleRect = event.currentTarget.getBoundingClientRect();
    const widgetStyle = getComputedStyle(widgetRef.current);
    const viewportOffsetX = widgetRect.left - (Number.parseFloat(widgetStyle.left) || widgetRect.left);
    const viewportOffsetY = widgetRect.top - (Number.parseFloat(widgetStyle.top) || widgetRect.top);
    dragRef.current = {
      pointerId: event.pointerId,
      offsetX: event.clientX - widgetRect.left,
      offsetY: event.clientY - widgetRect.top,
      dragging: false,
      startX: event.clientX,
      startY: event.clientY,
      source,
      restorePosition: source === 'launcher' ? { left: handleRect.left - viewportOffsetX, top: handleRect.top - viewportOffsetY } : null,
      viewportOffsetX,
      viewportOffsetY,
    };
    widgetRef.current.setPointerCapture(event.pointerId);
  }, []);

  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !widgetRef.current) return;
    const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (distance <= 6 && !drag.dragging) return;
    drag.dragging = true;
    const rect = widgetRef.current.getBoundingClientRect();
    setPosition(
      constrainPosition(
        event.clientX - drag.offsetX - drag.viewportOffsetX,
        event.clientY - drag.offsetY - drag.viewportOffsetY,
        rect.width,
        rect.height
      )
    );
  }, []);

  const finishDrag = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !widgetRef.current) return;
    if (widgetRef.current.hasPointerCapture(event.pointerId)) {
      widgetRef.current.releasePointerCapture(event.pointerId);
    }
    if (drag.source === 'launcher' && !drag.dragging) {
      launcherPositionRef.current = drag.restorePosition;
      setOpen(true);
    }
    dragRef.current = null;
  }, []);

  const closePanel = useCallback(() => {
    const restorePosition = launcherPositionRef.current;
    setOpen(false);
    if (restorePosition) {
      window.requestAnimationFrame(() => setPosition(restorePosition));
    }
  }, []);

  return {
    open,
    setOpen,
    closePanel,
    widgetRef,
    widgetStyle,
    startDrag,
    handlePointerMove,
    finishDrag,
  };
};

function constrainPosition(left: number, top: number, width: number, height: number): FloatingWidgetPosition {
  if (typeof window === 'undefined') {
    return { left, top };
  }
  const margin = 12;
  const maxLeft = Math.max(margin, window.innerWidth - width - margin);
  const maxTop = Math.max(margin, window.innerHeight - height - margin);
  return {
    left: Math.min(Math.max(left, margin), maxLeft),
    top: Math.min(Math.max(top, margin), maxTop),
  };
}
