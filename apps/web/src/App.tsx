import { useEffect, useState, useCallback } from 'react';
import { api } from '@/api/client';
import { Application } from '@/api/types';
import { Layout } from '@/components/layout/Layout';
import { NavigationPage } from '@/components/layout/Sidebar';

// 11 Core Pages
import { Overview } from '@/pages/Overview';
import { Applications } from '@/pages/Applications';
import { Architecture } from '@/pages/Architecture';
import { RiskAssessment } from '@/pages/RiskAssessment';
import { TestingAgents } from '@/pages/TestingAgents';
import { TestExecutions } from '@/pages/TestExecutions';
import { ChaosExperiments } from '@/pages/ChaosExperiments';
import { Observability } from '@/pages/Observability';
import { FailureIntelligence } from '@/pages/FailureIntelligence';
import { Reports } from '@/pages/Reports';
import { Settings } from '@/pages/Settings';

export function App() {
  const [currentPage, setCurrentPage] = useState<NavigationPage>('overview');
  const [applications, setApplications] = useState<Application[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);
  const [apiConnected, setApiConnected] = useState(false);
  const [activeRole, setActiveRole] = useState<'admin' | 'operator' | 'viewer'>('operator');

  // Load platform state & applications
  const loadInitialState = useCallback(async () => {
    try {
      const [healthRes, appsRes] = await Promise.allSettled([
        api.getHealth(),
        api.getApplications(),
      ]);

      if (healthRes.status === 'fulfilled') {
        setApiConnected(true);
      } else {
        setApiConnected(false);
      }

      if (appsRes.status === 'fulfilled' && appsRes.value.items) {
        setApplications(appsRes.value.items);
        if (appsRes.value.items.length > 0 && !selectedAppId) {
          setSelectedAppId(appsRes.value.items[0].application_id);
        }
      } else {
        // Fallback demo app if backend has no registered apps yet
        const demoApp: Application = {
          application_id: 'app-checkout-01',
          name: 'checkout-service',
          source_type: 'directory',
          source_location: './services/checkout',
          status: 'analyzed',
          registered_at: new Date().toISOString(),
          services_count: 5,
          apis_count: 14,
          technologies: ['FastAPI', 'PostgreSQL', 'Kafka', 'Redis'],
        };
        setApplications([demoApp]);
        if (!selectedAppId) {
          setSelectedAppId(demoApp.application_id);
        }
      }
    } catch {
      setApiConnected(false);
    }
  }, [selectedAppId]);

  useEffect(() => {
    loadInitialState();
  }, [loadInitialState]);

  const handleChangeRole = (newRole: 'admin' | 'operator' | 'viewer') => {
    setActiveRole(newRole);
    const key =
      newRole === 'admin'
        ? 'admin-key-supersecret'
        : newRole === 'operator'
        ? 'operator-key-secret'
        : 'viewer-key-public';
    api.setApiKey(key);
  };

  const renderActivePage = () => {
    switch (currentPage) {
      case 'overview':
        return (
          <Overview
            applications={applications}
            onNavigate={setCurrentPage}
            onRefresh={loadInitialState}
            selectedAppId={selectedAppId}
          />
        );
      case 'applications':
        return (
          <Applications
            applications={applications}
            selectedAppId={selectedAppId}
            onSelectApp={setSelectedAppId}
            onNavigate={setCurrentPage}
            onRefresh={loadInitialState}
          />
        );
      case 'architecture':
        return (
          <Architecture
            applications={applications}
            selectedAppId={selectedAppId}
            onSelectApp={setSelectedAppId}
            onNavigate={setCurrentPage}
          />
        );
      case 'risks':
        return (
          <RiskAssessment
            applications={applications}
            selectedAppId={selectedAppId}
            onSelectApp={setSelectedAppId}
            onNavigate={setCurrentPage}
          />
        );
      case 'testing-agents':
        return (
          <TestingAgents
            applications={applications}
            selectedAppId={selectedAppId}
            onSelectApp={setSelectedAppId}
            onNavigate={setCurrentPage}
          />
        );
      case 'test-executions':
        return (
          <TestExecutions
            applications={applications}
            selectedAppId={selectedAppId}
            onSelectApp={setSelectedAppId}
            onNavigate={setCurrentPage}
          />
        );
      case 'chaos-experiments':
        return (
          <ChaosExperiments
            applications={applications}
            selectedAppId={selectedAppId}
            onSelectApp={setSelectedAppId}
            onNavigate={setCurrentPage}
            activeRole={activeRole}
          />
        );
      case 'observability':
        return (
          <Observability
            applications={applications}
            selectedAppId={selectedAppId}
            onSelectApp={setSelectedAppId}
            onNavigate={setCurrentPage}
          />
        );
      case 'failure-intelligence':
        return (
          <FailureIntelligence
            applications={applications}
            selectedAppId={selectedAppId}
            onSelectApp={setSelectedAppId}
            onNavigate={setCurrentPage}
          />
        );
      case 'reports':
        return (
          <Reports
            applications={applications}
            selectedAppId={selectedAppId}
            onSelectApp={setSelectedAppId}
            onNavigate={setCurrentPage}
          />
        );
      case 'settings':
        return (
          <Settings
            apiConnected={apiConnected}
            activeRole={activeRole}
            onChangeRole={handleChangeRole}
            onRefreshHealth={loadInitialState}
          />
        );
      default:
        return (
          <Overview
            applications={applications}
            onNavigate={setCurrentPage}
            onRefresh={loadInitialState}
            selectedAppId={selectedAppId}
          />
        );
    }
  };

  return (
    <Layout
      currentPage={currentPage}
      onNavigate={setCurrentPage}
      applications={applications}
      selectedAppId={selectedAppId}
      onSelectApp={setSelectedAppId}
      apiConnected={apiConnected}
      activeRole={activeRole}
      onChangeRole={handleChangeRole}
    >
      {renderActivePage()}
    </Layout>
  );
}

export default App;

