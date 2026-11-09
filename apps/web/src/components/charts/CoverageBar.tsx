import { cn } from '@/utils/cn';

interface CoverageItem {
  category: string;
  covered: number;
  total: number;
  color?: string;
}

interface CoverageBarProps {
  items: CoverageItem[];
  title?: string;
  className?: string;
}

export function CoverageBar({ items, title = 'Test Coverage Breakdown', className }: CoverageBarProps) {
  const totalItems = items.reduce((acc, curr) => acc + curr.total, 0);
  const totalCovered = items.reduce((acc, curr) => acc + curr.covered, 0);
  const overallPercentage = totalItems > 0 ? Math.round((totalCovered / totalItems) * 100) : 0;

  const defaultColors = ['#06b6d4', '#10b981', '#3b82f6', '#8b5cf6', '#f59e0b'];

  return (
    <div className={cn('rounded-xl border border-border bg-surface-200/90 p-4 shadow-sm', className)}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wide">{title}</span>
        <span className="text-sm font-bold font-mono text-accent-cyan">{overallPercentage}%</span>
      </div>

      {/* Stacked Progress Bar */}
      <div className="h-2.5 w-full bg-surface-300 rounded-full overflow-hidden flex">
        {items.map((item, index) => {
          const widthPercent = totalItems > 0 ? (item.covered / totalItems) * 100 : 0;
          return (
            <div
              key={item.category}
              style={{
                width: `${widthPercent}%`,
                backgroundColor: item.color || defaultColors[index % defaultColors.length],
              }}
              className="h-full transition-all duration-300"
              title={`${item.category}: ${item.covered}/${item.total} (${Math.round(
                (item.covered / (item.total || 1)) * 100
              )}%)`}
            />
          );
        })}
      </div>

      {/* Legend list */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-4 text-[11px]">
        {items.map((item, index) => {
          const pct = item.total > 0 ? Math.round((item.covered / item.total) * 100) : 0;
          return (
            <div key={item.category} className="flex items-center gap-2">
              <span
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{ backgroundColor: item.color || defaultColors[index % defaultColors.length] }}
              />
              <span className="text-slate-400 truncate">{item.category}:</span>
              <span className="font-mono font-medium text-slate-200">
                {item.covered}/{item.total} <span className="text-slate-500">({pct}%)</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

