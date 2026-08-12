import { createContext, ReactNode, useContext, useMemo, useState } from 'react';

export interface MobileDetailActions {
  liked: boolean;
  primaryLabel: string;
  primaryDisabled?: boolean;
  onLike: () => void;
  onPrimary: () => void;
}

interface MobileBottomBarContextValue {
  detailActions: MobileDetailActions | null;
  setDetailActions: (actions: MobileDetailActions | null) => void;
}

const MobileBottomBarContext = createContext<MobileBottomBarContextValue | null>(null);

export function MobileBottomBarProvider({ children }: { children: ReactNode }) {
  const [detailActions, setDetailActions] = useState<MobileDetailActions | null>(null);
  const value = useMemo(() => ({ detailActions, setDetailActions }), [detailActions]);
  return (
    <MobileBottomBarContext.Provider value={value}>{children}</MobileBottomBarContext.Provider>
  );
}

export function useMobileBottomBar() {
  const context = useContext(MobileBottomBarContext);
  if (!context) {
    throw new Error('useMobileBottomBar must be used within MobileBottomBarProvider');
  }
  return context;
}
