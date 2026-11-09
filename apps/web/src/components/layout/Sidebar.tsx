import React from 'react';
import { cn } from '@/utils/cn';
import {
  LayoutDashboard,
  Layers,
  Network,
  ShieldAlert,
  Bot,
  PlayCircle,
  Flame,
  Activity,
  AlertTriangle,
  FileText,
  Settings,
  ChevronLeft,
  ChevronRight,
  Radio,
} from 'lucide-react';

export type NavigationPage =
  | 'overview'
  | 'applications'
  | 'architecture'
  | 'risks'
  | 'testing-agents'
  | 'test-executions'
  | 'chaos-experiments'
  | 'observability'
  | 'failure-intelligence'
  | 'reports'
  | 'settings';

interface SidebarProps {
  currentPage: NavigationPage;
  onNavigate: (page: NavigationPage) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  apiConnected: boolean;
}

export const NAV_ITEMS: Array<{
  id: NavigationPage;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
}> = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'applications', label: 'Applications', icon: Layers },
  { id: 'architecture', label: 'Architecture', icon: Network },
  { id: 'risks', label: 'Risk Assessment', icon: ShieldAlert },
  { id: 'testing-agents', label: 'Testing Agents', icon: Bot },
  { id: 'test-executions', label: 'Test Executions', icon: PlayCircle },
  { id: 'chaos-experiments', label: 'Chaos Experiments', icon: Flame, badge: 'Dry-Run' },
  { id: 'observability', label: 'Observability', icon: Activity },
  { id: 'failure-intelligence', label: 'Failure Intelligence', icon: AlertTriangle },
  { id: 'reports', label: 'Reports', icon: FileText },
  { id: 'settings', label: 'Settings', icon: Settings },
];

export function Sidebar({ currentPage, onNavigate, collapsed, onToggleCollapse, apiConnected }: SidebarProps) {
  return (
    <aside
      className={cn(
        'relative flex flex-col border-r border-border bg-surface-300 transition-all duration-200 select-none z-30 shrink-0',
        collapsed ? 'w-16' : 'w-64'
      )}
    >
      {/* Brand Header */}
      <div className="flex h-14 items-center justify-between px-3 border-b border-border">
        {!collapsed && (
          <div className="flex items-center gap-2.5 overflow-hidden pl-1">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-accent-cyan shadow-md shadow-primary/20 shrink-0">
              <Radio className="h-4 w-4 text-white animate-pulse" />
            </div>
            <div className="flex flex-col truncate">
              <span className="text-sm font-bold tracking-wider text-slate-100 uppercase">CHAOS-INTEL</span>
              <span className="text-[10px] text-muted-foreground font-mono">Platform v2.4</span>
            </div>
          </div>
        )}
        {collapsed && (
          <div className="mx-auto flex h-8 w-8 items-center justify-center rounded-lg bg-primary shadow-md">
            <Radio className="h-4 w-4 text-white" />
          </div>
        )}
        <button
          onClick={onToggleCollapse}
          className={cn(
            'flex h-7 w-7 items-center justify-center rounded-md border border-border bg-surface-200 text-slate-400 hover:text-white hover:bg-surface-100 transition-colors',
            collapsed && 'hidden'
          )}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
      </div>

      {/* Navigation list */}
      <nav className="flex-1 space-y-1 p-2 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = currentPage === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              title={collapsed ? item.label : undefined}
              className={cn(
                'group flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-xs font-medium transition-colors text-left',
                isActive
                  ? 'bg-primary/15 text-accent-cyan border border-primary/30 shadow-sm'
                  : 'text-slate-400 hover:bg-surface-200 hover:text-slate-200'
              )}
            >
              <Icon
                className={cn(
                  'h-4 w-4 shrink-0 transition-colors',
                  isActive ? 'text-accent-cyan' : 'text-slate-400 group-hover:text-slate-200'
                )}
              />
              {!collapsed && (
                <div className="flex flex-1 items-center justify-between overflow-hidden">
                  <span className="truncate">{item.label}</span>
                  {item.badge && (
                    <span className="rounded bg-amber-950/80 px-1.5 py-0.5 text-[9px] font-mono font-medium text-amber-300 border border-amber-800/60">
                      {item.badge}
                    </span>
                  )}
                </div>
              )}
            </button>
          );
        })}
      </nav>

      {/* Footer System Status */}
      <div className="border-t border-border p-3">
        {collapsed ? (
          <div className="flex justify-center" title={apiConnected ? 'API Connected' : 'API Disconnected'}>
            <span
              className={cn('h-2.5 w-2.5 rounded-full', apiConnected ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500')}
            />
          </div>
        ) : (
          <div className="flex items-center justify-between rounded-lg bg-surface-200 p-2 border border-border/60">
            <div className="flex items-center gap-2">
              <span
                className={cn('h-2 w-2 rounded-full', apiConnected ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500')}
              />
              <span className="text-[11px] font-medium text-slate-300">
                {apiConnected ? 'Backend Online' : 'Backend Disconnected'}
              </span>
            </div>
            <button
              onClick={onToggleCollapse}
              className="text-slate-500 hover:text-slate-300"
              title="Collapse sidebar"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {collapsed && (
        <button
          onClick={onToggleCollapse}
          className="absolute -right-3 top-16 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface-200 text-slate-400 hover:text-white shadow-md"
          title="Expand sidebar"
        >
          <ChevronRight className="h-3 w-3" />
        </button>
      )}
    </aside>
  );
}

