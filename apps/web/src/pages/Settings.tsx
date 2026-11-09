import React, { useState } from 'react';
import { api } from '@/api/client';
import { HealthStatus } from '@/api/types';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { StatusIndicator } from '@/components/ui/StatusIndicator';
import {
  Settings as SettingsIcon,
  Server,
  Key,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Cpu,
  Layers,
  Terminal,
} from 'lucide-react';

interface SettingsProps {
  apiConnected: boolean;
  activeRole: 'admin' | 'operator' | 'viewer';
  onChangeRole: (role: 'admin' | 'operator' | 'viewer') => void;
  onRefreshHealth: () => void;
}

export function Settings({
  apiConnected,
  activeRole,
  onChangeRole,
  onRefreshHealth,
}: SettingsProps) {
  const [apiUrl, setApiUrl] = useState(api.getBaseUrl());
  const [apiKey, setApiKey] = useState(api.getApiKey());
  const [healthResult, setHealthResult] = useState<HealthStatus | null>(null);
  const [testingConnection, setTestingConnection] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleSaveSettings = (e: React.FormEvent) => {
    e.preventDefault();
    api.setBaseUrl(apiUrl);
    api.setApiKey(apiKey);
    setStatusMessage({ type: 'success', text: 'API settings updated and persisted to localStorage.' });
    onRefreshHealth();
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    setStatusMessage(null);
    try {
      const res = await api.getHealth();
      setHealthResult(res);
      setStatusMessage({ type: 'success', text: 'Connection successful. Backend reported status HEALTHY.' });
      onRefreshHealth();
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: err.message || 'Connection test failed.' });
    } finally {
      setTestingConnection(false);
    }
  };

  const handleSelectRolePreset = (role: 'admin' | 'operator' | 'viewer') => {
    onChangeRole(role);
    const keyPreset =
      role === 'admin'
        ? 'admin-key-supersecret'
        : role === 'operator'
        ? 'operator-key-secret'
        : 'viewer-key-public';
    setApiKey(keyPreset);
    api.setApiKey(keyPreset);
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/80">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">Platform & Connectivity Settings</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Configure backend API gateway endpoint, role authentication credentials, and diagnostic probes.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusIndicator
            status={apiConnected ? 'online' : 'error'}
            label={apiConnected ? 'API Connected' : 'Disconnected'}
          />
        </div>
      </div>

      {/* Status Alert Banner */}
      {statusMessage && (
        <div
          className={`p-3 rounded-lg border text-xs flex items-center justify-between ${
            statusMessage.type === 'success'
              ? 'bg-emerald-950/40 border-emerald-800 text-emerald-300'
              : 'bg-rose-950/40 border-rose-800 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-2">
            {statusMessage.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
            ) : (
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
            )}
            <span>{statusMessage.text}</span>
          </div>
          <button
            onClick={() => setStatusMessage(null)}
            className="text-slate-400 hover:text-white text-xs underline ml-4"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Main Form & Role Matrix */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* API Endpoint Configuration */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader className="pb-3 border-b border-border/60">
              <CardTitle className="text-sm">API Gateway Connectivity</CardTitle>
              <p className="text-xs text-muted-foreground mt-0.5">
                Target endpoint for all FastAPI `/api/v1/` REST requests.
              </p>
            </CardHeader>
            <CardContent className="p-4">
              <form onSubmit={handleSaveSettings} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Backend Base URL
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      required
                      value={apiUrl}
                      onChange={(e) => setApiUrl(e.target.value)}
                      placeholder="http://127.0.0.1:8000/api/v1"
                      className="flex-1 h-9 rounded-lg bg-surface-100 border border-border px-3 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-primary font-mono"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={handleTestConnection}
                      loading={testingConnection}
                      icon={<Server className="w-3.5 h-3.5" />}
                    >
                      Test Health
                    </Button>
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Default: <code className="text-slate-300 font-mono">http://127.0.0.1:8000/api/v1</code>
                  </p>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    API Authentication Key
                  </label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="Enter API key"
                    className="w-full h-9 rounded-lg bg-surface-100 border border-border px-3 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-primary font-mono"
                  />
                </div>

                {/* Role Switcher Presets */}
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Select Role Preset (Test Environment)
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {(['operator', 'admin', 'viewer'] as const).map((role) => (
                      <button
                        key={role}
                        type="button"
                        onClick={() => handleSelectRolePreset(role)}
                        className={`p-2 rounded-lg border text-xs font-medium text-center transition-all ${
                          activeRole === role
                            ? 'bg-primary/20 border-primary text-accent-cyan font-bold shadow-sm'
                            : 'bg-surface-300/80 border-border/60 text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        <div className="capitalize">{role}</div>
                        <span className="text-[10px] font-mono text-slate-500">
                          {role === 'admin' ? 'All Grants' : role === 'operator' ? 'Execution' : 'Read Only'}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="pt-2 flex justify-end gap-2 border-t border-border/60">
                  <Button type="submit" variant="primary" size="sm">
                    Save Changes
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>

        {/* Role Privileges & Invariants */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3 border-b border-border/60">
              <CardTitle className="text-sm">Role Privilege Matrix</CardTitle>
            </CardHeader>
            <CardContent className="p-4 space-y-3">
              <div className="rounded-lg bg-surface-300 p-3 border border-border/60 space-y-2 text-xs">
                <div className="flex items-center justify-between text-slate-300">
                  <span>Application Analysis</span>
                  <Badge variant="success">Viewer+</Badge>
                </div>
                <div className="flex items-center justify-between text-slate-300">
                  <span>Test Plan Execution</span>
                  <Badge variant="cyan">Operator+</Badge>
                </div>
                <div className="flex items-center justify-between text-slate-300">
                  <span>Chaos Approval Grant</span>
                  <Badge variant="warning">Admin Only</Badge>
                </div>
                <div className="flex items-center justify-between text-slate-300">
                  <span>Job Cancellation</span>
                  <Badge variant="warning">Admin Only</Badge>
                </div>
              </div>

              <div className="p-3 rounded-lg bg-surface-300/60 border border-border/60 text-[11px] text-slate-400 space-y-1">
                <div className="font-semibold text-slate-300 flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-accent-cyan" />
                  Security Fencing Guarantee
                </div>
                <p className="leading-relaxed">
                  Authentication tokens are transmitted via the <code className="text-slate-300 font-mono">X-API-Key</code> request header.
                  Role escalation is validated on each invocation.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

