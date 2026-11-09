import { useState } from 'react';
import { Application } from '@/api/types';
import { api } from '@/api/client';
import { NavigationPage } from './Sidebar';
import {
  Bell,
  CheckCircle2,
  ChevronRight,
  Fingerprint,
  Key,
  ShieldCheck,
  User,
  AlertCircle,
} from 'lucide-react';

interface HeaderProps {
  currentPage: NavigationPage;
  applications: Application[];
  selectedAppId: string | null;
  onSelectApp: (appId: string) => void;
  notifications: Array<{ id: string; title: string; message: string; type: 'info' | 'warn' | 'error'; time: string }>;
  onClearNotifications: () => void;
  activeRole: 'admin' | 'operator' | 'viewer';
  onChangeRole: (role: 'admin' | 'operator' | 'viewer') => void;
  correlationId: string;
}

export function Header({
  currentPage,
  applications,
  selectedAppId,
  onSelectApp,
  notifications,
  onClearNotifications,
  activeRole,
  onChangeRole,
  correlationId,
}: HeaderProps) {
  const [showNotifications, setShowNotifications] = useState(false);
  const [showRoleMenu, setShowRoleMenu] = useState(false);

  const formatPageTitle = (page: NavigationPage) => {
    return page
      .split('-')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const selectedApp = applications.find((a) => a.application_id === selectedAppId);

  return (
    <header className="h-14 border-b border-border bg-surface-300/80 px-4 flex items-center justify-between backdrop-blur-sm z-20">
      {/* Left: Breadcrumbs & Application Selector */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="text-slate-500 font-mono">Platform</span>
          <ChevronRight className="w-3.5 h-3.5 text-slate-600" />
          <span className="font-medium text-slate-200">{formatPageTitle(currentPage)}</span>
        </div>

        {applications.length > 0 && (
          <div className="hidden sm:flex items-center gap-2 pl-3 border-l border-border/80">
            <span className="text-xs text-slate-400">Scope:</span>
            <select
              value={selectedAppId || ''}
              onChange={(e) => onSelectApp(e.target.value)}
              className="bg-surface-200 border border-border rounded-md px-2.5 py-1 text-xs text-slate-200 focus:outline-none focus:border-primary font-medium"
            >
              <option value="">-- All Applications --</option>
              {applications.map((app) => (
                <option key={app.application_id} value={app.application_id}>
                  {app.name} ({app.technologies?.slice(0, 2).join(', ') || 'Service'})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Right: Correlation ID, Role Switcher, Notifications, User */}
      <div className="flex items-center gap-2.5">
        {/* Active Correlation ID pill */}
        <div
          className="hidden md:flex items-center gap-1.5 bg-surface-200/90 border border-border/70 rounded-md px-2 py-1 font-mono text-[10px] text-slate-400"
          title={`Active Correlation ID: ${correlationId}`}
        >
          <Fingerprint className="w-3 h-3 text-accent-cyan" />
          <span className="truncate max-w-[120px]">{correlationId}</span>
        </div>

        {/* Role & Auth Key Switcher */}
        <div className="relative">
          <button
            onClick={() => setShowRoleMenu(!showRoleMenu)}
            className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-surface-200 border border-border text-xs text-slate-300 hover:text-white hover:bg-surface-100 transition-colors"
            title="Switch Auth Role"
          >
            <ShieldCheck className="w-3.5 h-3.5 text-accent-cyan" />
            <span className="capitalize font-medium">{activeRole}</span>
          </button>

          {showRoleMenu && (
            <div className="absolute right-0 mt-2 w-52 rounded-lg border border-border bg-surface-200 p-2 shadow-xl z-50 animate-in fade-in zoom-in-95 duration-100">
              <div className="px-2 py-1 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                Active Role
              </div>
              <div className="space-y-1 mt-1">
                {(['operator', 'admin', 'viewer'] as const).map((role) => (
                  <button
                    key={role}
                    onClick={() => {
                      onChangeRole(role);
                      setShowRoleMenu(false);
                    }}
                    className={`flex items-center justify-between w-full px-2 py-1.5 text-xs rounded-md transition-colors text-left ${
                      activeRole === role ? 'bg-primary/20 text-accent-cyan font-semibold' : 'text-slate-300 hover:bg-surface-100'
                    }`}
                  >
                    <span className="capitalize">{role}</span>
                    {activeRole === role && <CheckCircle2 className="w-3.5 h-3.5 text-accent-cyan" />}
                  </button>
                ))}
              </div>
              <div className="border-t border-border mt-2 pt-2 px-2 text-[10px] text-muted-foreground">
                <span className="font-mono">admin</span> has execution and chaos approval privileges.
              </div>
            </div>
          )}
        </div>

        {/* Notifications Popover */}
        <div className="relative">
          <button
            onClick={() => setShowNotifications(!showNotifications)}
            className="relative p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-surface-200 transition-colors"
            title="Notifications"
          >
            <Bell className="w-4 h-4" />
            {notifications.length > 0 && (
              <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-accent-rose animate-ping" />
            )}
            {notifications.length > 0 && (
              <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-accent-rose" />
            )}
          </button>

          {showNotifications && (
            <div className="absolute right-0 mt-2 w-80 rounded-xl border border-border bg-surface-200 shadow-2xl z-50 overflow-hidden">
              <div className="flex items-center justify-between p-3 border-b border-border bg-surface-300/60">
                <span className="text-xs font-semibold text-slate-200">Alerts & Notifications</span>
                {notifications.length > 0 && (
                  <button
                    onClick={onClearNotifications}
                    className="text-[11px] text-accent-cyan hover:underline"
                  >
                    Clear All
                  </button>
                )}
              </div>
              <div className="max-h-72 overflow-y-auto p-2 space-y-1.5">
                {notifications.length === 0 ? (
                  <div className="py-6 text-center text-xs text-muted-foreground">No new notifications</div>
                ) : (
                  notifications.map((n) => (
                    <div
                      key={n.id}
                      className="p-2.5 rounded-lg bg-surface-300/80 border border-border/60 text-xs flex gap-2.5 items-start"
                    >
                      {n.type === 'error' ? (
                        <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                      ) : (
                        <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                      )}
                      <div className="flex-1 overflow-hidden">
                        <div className="font-medium text-slate-200">{n.title}</div>
                        <div className="text-slate-400 text-[11px] mt-0.5 line-clamp-2">{n.message}</div>
                        <div className="text-[10px] text-slate-500 mt-1 font-mono">{n.time}</div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

