import React, { createContext, useContext, useState } from 'react';
import { cn } from '@/utils/cn';

interface TabsContextType {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

const TabsContext = createContext<TabsContextType | undefined>(undefined);

export interface TabsProps {
  defaultValue: string;
  value?: string;
  onValueChange?: (value: string) => void;
  className?: string;
  children: React.ReactNode;
}

export function Tabs({ defaultValue, value, onValueChange, className, children }: TabsProps) {
  const [internalValue, setInternalValue] = useState(defaultValue);
  const activeTab = value !== undefined ? value : internalValue;

  const setActiveTab = (newTab: string) => {
    if (value === undefined) setInternalValue(newTab);
    onValueChange?.(newTab);
  };

  return (
    <TabsContext.Provider value={{ activeTab, setActiveTab }}>
      <div className={cn('w-full flex flex-col', className)}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 p-1 rounded-lg bg-surface-300 border border-border/80 text-muted-foreground w-fit',
        className
      )}
    >
      {children}
    </div>
  );
}

export function TabsTrigger({
  value,
  children,
  className,
  badge,
}: {
  value: string;
  children: React.ReactNode;
  className?: string;
  badge?: number | string;
}) {
  const context = useContext(TabsContext);
  if (!context) throw new Error('TabsTrigger must be used within Tabs');

  const isActive = context.activeTab === value;

  return (
    <button
      type="button"
      onClick={() => context.setActiveTab(value)}
      className={cn(
        'inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md transition-all select-none',
        isActive
          ? 'bg-surface-100 text-slate-100 shadow-sm border border-border/60 font-semibold'
          : 'text-slate-400 hover:text-slate-200 hover:bg-surface-200/50',
        className
      )}
    >
      <span>{children}</span>
      {badge !== undefined && (
        <span
          className={cn(
            'px-1.5 py-0.2 rounded-full text-[10px]',
            isActive ? 'bg-primary/20 text-accent-cyan' : 'bg-surface-200 text-muted-foreground'
          )}
        >
          {badge}
        </span>
      )}
    </button>
  );
}

export function TabsContent({
  value,
  children,
  className,
}: {
  value: string;
  children: React.ReactNode;
  className?: string;
}) {
  const context = useContext(TabsContext);
  if (!context) throw new Error('TabsContent must be used within Tabs');

  if (context.activeTab !== value) return null;

  return <div className={cn('mt-4 focus-visible:outline-none', className)}>{children}</div>;
}

