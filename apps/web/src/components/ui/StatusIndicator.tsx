import { cn } from '@/utils/cn';

export interface StatusIndicatorProps {
  status: 'online' | 'offline' | 'running' | 'warning' | 'error' | 'neutral';
  label?: string;
  className?: string;
  pulse?: boolean;
}

export function StatusIndicator({ status, label, className, pulse = true }: StatusIndicatorProps) {
  const statusColors = {
    online: 'bg-emerald-500',
    running: 'bg-cyan-500',
    warning: 'bg-amber-500',
    error: 'bg-rose-500',
    offline: 'bg-slate-500',
    neutral: 'bg-slate-400',
  };

  const pulseColors = {
    online: 'bg-emerald-400',
    running: 'bg-cyan-400',
    warning: 'bg-amber-400',
    error: 'bg-rose-400',
    offline: 'bg-transparent',
    neutral: 'bg-transparent',
  };

  return (
    <div className={cn('inline-flex items-center gap-2', className)}>
      <span className="relative flex h-2.5 w-2.5">
        {pulse && status !== 'offline' && status !== 'neutral' && (
          <span
            className={cn(
              'animate-ping absolute inline-flex h-full w-full rounded-full opacity-75',
              pulseColors[status]
            )}
          />
        )}
        <span className={cn('relative inline-flex rounded-full h-2.5 w-2.5', statusColors[status])} />
      </span>
      {label && <span className="text-xs text-slate-300 font-medium">{label}</span>}
    </div>
  );
}

