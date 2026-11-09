import React from 'react';
import { cn } from '@/utils/cn';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'success' | 'warning' | 'destructive' | 'outline' | 'cyan' | 'purple';
  size?: 'sm' | 'md';
}

export function Badge({ className, variant = 'default', size = 'sm', children, ...props }: BadgeProps) {
  const variants = {
    default: 'bg-surface-50 text-slate-300 border-border',
    success: 'bg-emerald-950/60 text-emerald-400 border-emerald-800/60',
    warning: 'bg-amber-950/60 text-amber-400 border-amber-800/60',
    destructive: 'bg-rose-950/60 text-rose-400 border-rose-800/60',
    outline: 'bg-transparent text-slate-400 border-border',
    cyan: 'bg-cyan-950/60 text-cyan-400 border-cyan-800/60',
    purple: 'bg-purple-950/60 text-purple-400 border-purple-800/60',
  };

  const sizes = {
    sm: 'px-2 py-0.5 text-[11px] font-medium leading-none',
    md: 'px-2.5 py-1 text-xs font-medium',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border tracking-wide uppercase',
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}

