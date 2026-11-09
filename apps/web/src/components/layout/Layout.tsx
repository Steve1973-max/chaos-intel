import React, { useState } from 'react';
import { Sidebar, NavigationPage } from './Sidebar';
import { Header } from './Header';
import { Application } from '@/api/types';

interface LayoutProps {
  currentPage: NavigationPage;
  onNavigate: (page: NavigationPage) => void;
  applications: Application[];
  selectedAppId: string | null;
  onSelectApp: (appId: string) => void;
  apiConnected: boolean;
  activeRole: 'admin' | 'operator' | 'viewer';
  onChangeRole: (role: 'admin' | 'operator' | 'viewer') => void;
  children: React.ReactNode;
}

export function Layout({
  currentPage,
  onNavigate,
  applications,
  selectedAppId,
  onSelectApp,
  apiConnected,
  activeRole,
  onChangeRole,
  children,
}: LayoutProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [notifications, setNotifications] = useState<
    Array<{ id: string; title: string; message: string; type: 'info' | 'warn' | 'error'; time: string }>
  >([
    {
      id: 'init-1',
      title: 'Platform Initialized',
      message: 'CHAOS-INTEL backend platform v2.4 connected and ready.',
      type: 'info',
      time: 'Just now',
    },
  ]);
  const [correlationId] = useState(() => `corr-${Math.random().toString(36).substring(2, 9)}`);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-slate-100 font-sans antialiased">
      {/* Sidebar */}
      <Sidebar
        currentPage={currentPage}
        onNavigate={onNavigate}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed(!collapsed)}
        apiConnected={apiConnected}
      />

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header
          currentPage={currentPage}
          applications={applications}
          selectedAppId={selectedAppId}
          onSelectApp={onSelectApp}
          notifications={notifications}
          onClearNotifications={() => setNotifications([])}
          activeRole={activeRole}
          onChangeRole={onChangeRole}
          correlationId={correlationId}
        />

        <main className="flex-1 overflow-y-auto p-6 bg-background">
          <div className="mx-auto max-w-7xl space-y-6">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

