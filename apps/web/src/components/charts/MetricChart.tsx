import React, { useMemo } from 'react';
import { cn } from '@/utils/cn';

export interface DataPoint {
  timestamp: string;
  value: number;
  label?: string;
}

interface MetricChartProps {
  title: string;
  description?: string;
  data: DataPoint[];
  unit?: string;
  color?: 'cyan' | 'emerald' | 'amber' | 'rose' | 'blue';
  currentValue?: string | number;
  threshold?: number;
  className?: string;
}

export function MetricChart({
  title,
  description,
  data,
  unit = '',
  color = 'cyan',
  currentValue,
  threshold,
  className,
}: MetricChartProps) {
  const colorMap = {
    cyan: { stroke: '#06b6d4', fill: 'url(#gradient-cyan)', bg: 'bg-cyan-500' },
    emerald: { stroke: '#10b981', fill: 'url(#gradient-emerald)', bg: 'bg-emerald-500' },
    amber: { stroke: '#f59e0b', fill: 'url(#gradient-amber)', bg: 'bg-amber-500' },
    rose: { stroke: '#f43f5e', fill: 'url(#gradient-rose)', bg: 'bg-rose-500' },
    blue: { stroke: '#3b82f6', fill: 'url(#gradient-blue)', bg: 'bg-blue-500' },
  };

  const chartTheme = colorMap[color] || colorMap.cyan;

  // Compute SVG dimensions and normalized coordinates
  const { pathData, areaData, minVal, maxVal } = useMemo(() => {
    if (!data || data.length === 0) {
      return { pathData: '', areaData: '', minVal: 0, maxVal: 100 };
    }

    const values = data.map((d) => d.value);
    const min = Math.min(...values);
    const max = Math.max(...values, threshold || 0);
    const range = max - min || 1;

    const width = 360;
    const height = 110;
    const padding = 10;

    const points = data.map((d, index) => {
      const x = padding + (index / (data.length - 1)) * (width - 2 * padding);
      const y = height - padding - ((d.value - min) / range) * (height - 2 * padding);
      return { x, y };
    });

    let p = `M ${points[0].x} ${points[0].y}`;
    for (let i = 1; i < points.length; i++) {
      // Smooth spline interpolation
      const prev = points[i - 1];
      const curr = points[i];
      const cx = (prev.x + curr.x) / 2;
      p += ` C ${cx} ${prev.y}, ${cx} ${curr.y}, ${curr.x} ${curr.y}`;
    }

    const first = points[0];
    const last = points[points.length - 1];
    const a = `${p} L ${last.x} ${height - padding} L ${first.x} ${height - padding} Z`;

    return { pathData: p, areaData: a, minVal: min, maxVal: max };
  }, [data, threshold]);

  const latestVal = currentValue !== undefined ? currentValue : data.length > 0 ? data[data.length - 1].value : 0;

  return (
    <div
      className={cn(
        'rounded-xl border border-border bg-surface-200/90 p-4 flex flex-col justify-between shadow-sm',
        className
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <span className="text-xs font-semibold text-slate-300 tracking-wide uppercase">{title}</span>
          {description && <p className="text-[11px] text-muted-foreground mt-0.5">{description}</p>}
        </div>
        <div className="text-right">
          <span className="text-lg font-bold font-mono text-slate-100">
            {latestVal}
            <span className="text-xs font-normal text-muted-foreground ml-1">{unit}</span>
          </span>
        </div>
      </div>

      {/* SVG Sparkline / Area Chart */}
      <div className="mt-4 relative h-28 w-full">
        <svg viewBox="0 0 360 110" preserveAspectRatio="none" className="w-full h-full overflow-visible">
          <defs>
            <linearGradient id="gradient-cyan" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.0" />
            </linearGradient>
            <linearGradient id="gradient-emerald" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
            </linearGradient>
            <linearGradient id="gradient-amber" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.0" />
            </linearGradient>
            <linearGradient id="gradient-rose" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.0" />
            </linearGradient>
            <linearGradient id="gradient-blue" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Threshold line */}
          {threshold !== undefined && maxVal > minVal && (
            <line
              x1="10"
              y1={110 - 10 - ((threshold - minVal) / (maxVal - minVal)) * 90}
              x2="350"
              y2={110 - 10 - ((threshold - minVal) / (maxVal - minVal)) * 90}
              stroke="#f43f5e"
              strokeDasharray="4 4"
              strokeWidth="1"
            />
          )}

          {/* Area under curve */}
          {areaData && <path d={areaData} fill={chartTheme.fill} />}

          {/* Line stroke */}
          {pathData && (
            <path
              d={pathData}
              fill="none"
              stroke={chartTheme.stroke}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
        </svg>
      </div>

      {/* Axis Footer */}
      <div className="flex justify-between items-center text-[10px] text-slate-500 font-mono mt-1 pt-2 border-t border-border/40">
        <span>{data[0]?.timestamp || '0m'}</span>
        <span>{data[Math.floor(data.length / 2)]?.timestamp || '15m'}</span>
        <span>{data[data.length - 1]?.timestamp || '30m'}</span>
      </div>
    </div>
  );
}

