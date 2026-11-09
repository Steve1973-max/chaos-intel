import React, { useState } from 'react';
import { Application } from '@/api/types';
import { api } from '@/api/client';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Modal } from '@/components/ui/Modal';
import { NavigationPage } from '@/components/layout/Sidebar';
import {
  Layers,
  Plus,
  Upload,
  Folder,
  Cpu,
  Globe,
  ArrowRight,
  RefreshCw,
  Network,
  ShieldAlert,
  Bot,
  CheckCircle2,
  AlertCircle,
  Clock,
} from 'lucide-react';

interface ApplicationsProps {
  applications: Application[];
  selectedAppId: string | null;
  onSelectApp: (appId: string) => void;
  onNavigate: (page: NavigationPage) => void;
  onRefresh: () => void;
}

export function Applications({
  applications,
  selectedAppId,
  onSelectApp,
  onNavigate,
  onRefresh,
}: ApplicationsProps) {
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState(false);
  const [regMode, setRegMode] = useState<'directory' | 'upload'>('directory');
  const [appName, setAppName] = useState('');
  const [sourceLocation, setSourceLocation] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);
  const [feedbackMsg, setFeedbackMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFeedbackMsg(null);
    try {
      if (regMode === 'directory') {
        if (!appName || !sourceLocation) {
          throw new Error('Please provide both application name and source directory path.');
        }
        await api.registerApplication({
          name: appName,
          source_location: sourceLocation,
          source_type: 'directory',
        });
      } else {
        if (!uploadFile) {
          throw new Error('Please select an archive file (.zip or .tar.gz).');
        }
        await api.uploadArchive(uploadFile);
      }

      setFeedbackMsg({ type: 'success', text: 'Application successfully registered.' });
      setIsRegisterModalOpen(false);
      setAppName('');
      setSourceLocation('');
      setUploadFile(null);
      onRefresh();
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to register application.' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleTriggerAnalysis = async (appId: string) => {
    setAnalyzingId(appId);
    try {
      await api.analyzeApplication(appId);
      setFeedbackMsg({
        type: 'success',
        text: 'Analysis job scheduled. Extracting architecture graph and calculating risk profile.',
      });
      onRefresh();
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to trigger application analysis.' });
    } finally {
      setAnalyzingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/80">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">Registered Applications</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Manage target source codebases, trigger AST static analysis, and inspect detected topologies.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Refresh
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsRegisterModalOpen(true)}
            icon={<Plus className="w-3.5 h-3.5" />}
          >
            Register Application
          </Button>
        </div>
      </div>

      {/* Status Feedback banner */}
      {feedbackMsg && (
        <div
          className={`p-3 rounded-lg border text-xs flex items-center justify-between ${
            feedbackMsg.type === 'success'
              ? 'bg-emerald-950/40 border-emerald-800 text-emerald-300'
              : 'bg-rose-950/40 border-rose-800 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-2">
            {feedbackMsg.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
            ) : (
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
            )}
            <span>{feedbackMsg.text}</span>
          </div>
          <button
            onClick={() => setFeedbackMsg(null)}
            className="text-slate-400 hover:text-white text-xs underline ml-4"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Applications Grid */}
      {applications.length === 0 ? (
        <Card>
          <CardContent className="py-12 flex flex-col items-center justify-center text-center">
            <div className="h-12 w-12 rounded-xl bg-surface-100 border border-border flex items-center justify-center text-slate-400 mb-3">
              <Layers className="w-6 h-6" />
            </div>
            <h3 className="text-sm font-semibold text-slate-200">No applications registered yet</h3>
            <p className="text-xs text-muted-foreground max-w-sm mt-1">
              Connect a local codebase or upload an application archive to begin intelligence analysis.
            </p>
            <Button
              variant="primary"
              size="sm"
              className="mt-4"
              onClick={() => setIsRegisterModalOpen(true)}
              icon={<Plus className="w-3.5 h-3.5" />}
            >
              Register First Application
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {applications.map((app) => {
            const isSelected = selectedAppId === app.application_id;
            const isAnalyzing = analyzingId === app.application_id || app.status === 'analyzing';

            return (
              <Card
                key={app.application_id}
                className={`transition-all ${
                  isSelected ? 'border-primary ring-1 ring-primary/40 bg-surface-100/90' : ''
                }`}
              >
                <CardHeader className="pb-3 flex flex-row items-start justify-between">
                  <div className="space-y-1 overflow-hidden">
                    <CardTitle className="text-base truncate">{app.name}</CardTitle>
                    <p className="text-[11px] font-mono text-muted-foreground truncate" title={app.source_location}>
                      {app.source_location}
                    </p>
                  </div>
                  <Badge
                    variant={
                      app.status === 'analyzed'
                        ? 'success'
                        : app.status === 'analyzing'
                        ? 'cyan'
                        : app.status === 'failed'
                        ? 'destructive'
                        : 'default'
                    }
                  >
                    {app.status}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Tech stack tags */}
                  <div className="flex flex-wrap gap-1">
                    {app.technologies && app.technologies.length > 0 ? (
                      app.technologies.map((tech) => (
                        <span
                          key={tech}
                          className="px-2 py-0.5 rounded bg-surface-300 text-[10px] font-mono text-slate-300 border border-border/50"
                        >
                          {tech}
                        </span>
                      ))
                    ) : (
                      <span className="text-[11px] text-slate-500 italic">No technologies detected yet</span>
                    )}
                  </div>

                  {/* Summary metrics */}
                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-border/60">
                    <div className="bg-surface-300/80 p-2 rounded-lg border border-border/40">
                      <span className="text-[10px] uppercase font-semibold text-muted-foreground">Services</span>
                      <div className="text-base font-bold font-mono text-slate-100">{app.services_count || 0}</div>
                    </div>
                    <div className="bg-surface-300/80 p-2 rounded-lg border border-border/40">
                      <span className="text-[10px] uppercase font-semibold text-muted-foreground">APIs</span>
                      <div className="text-base font-bold font-mono text-slate-100">{app.apis_count || 0}</div>
                    </div>
                  </div>

                  {/* Action buttons */}
                  <div className="space-y-2 pt-2">
                    <div className="flex items-center gap-2">
                      <Button
                        variant={isSelected ? 'secondary' : 'outline'}
                        size="sm"
                        className="flex-1 text-xs"
                        onClick={() => onSelectApp(app.application_id)}
                      >
                        {isSelected ? 'Selected Active' : 'Set as Scope'}
                      </Button>
                      <Button
                        variant="primary"
                        size="sm"
                        className="text-xs"
                        loading={isAnalyzing}
                        onClick={() => handleTriggerAnalysis(app.application_id)}
                        icon={<Cpu className="w-3.5 h-3.5" />}
                      >
                        Analyze
                      </Button>
                    </div>

                    {app.status === 'analyzed' && (
                      <div className="flex items-center justify-between text-[11px] text-accent-cyan pt-1">
                        <button
                          onClick={() => {
                            onSelectApp(app.application_id);
                            onNavigate('architecture');
                          }}
                          className="hover:underline flex items-center gap-1"
                        >
                          <Network className="w-3 h-3" /> Graph
                        </button>
                        <span className="text-slate-600">•</span>
                        <button
                          onClick={() => {
                            onSelectApp(app.application_id);
                            onNavigate('risks');
                          }}
                          className="hover:underline flex items-center gap-1"
                        >
                          <ShieldAlert className="w-3 h-3" /> Risks
                        </button>
                        <span className="text-slate-600">•</span>
                        <button
                          onClick={() => {
                            onSelectApp(app.application_id);
                            onNavigate('testing-agents');
                          }}
                          className="hover:underline flex items-center gap-1"
                        >
                          <Bot className="w-3 h-3" /> Tests
                        </button>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Application Registration Modal */}
      <Modal
        isOpen={isRegisterModalOpen}
        onClose={() => setIsRegisterModalOpen(false)}
        title="Register Target Application"
        description="Provide a local directory path or upload an archive for static AST analysis."
      >
        <form onSubmit={handleRegister} className="space-y-4">
          <div className="flex rounded-lg bg-surface-300 p-1 border border-border">
            <button
              type="button"
              onClick={() => setRegMode('directory')}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors flex items-center justify-center gap-1.5 ${
                regMode === 'directory' ? 'bg-surface-100 text-slate-100 shadow' : 'text-slate-400 hover:text-white'
              }`}
            >
              <Folder className="w-3.5 h-3.5" /> Local Directory
            </button>
            <button
              type="button"
              onClick={() => setRegMode('upload')}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors flex items-center justify-center gap-1.5 ${
                regMode === 'upload' ? 'bg-surface-100 text-slate-100 shadow' : 'text-slate-400 hover:text-white'
              }`}
            >
              <Upload className="w-3.5 h-3.5" /> Upload Archive
            </button>
          </div>

          {regMode === 'directory' ? (
            <>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Application Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. checkout-service or core-banking"
                  value={appName}
                  onChange={(e) => setAppName(e.target.value)}
                  className="w-full h-9 rounded-lg bg-surface-100 border border-border px-3 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Source Directory Path</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. C:/projects/checkout-service or ./services/auth"
                  value={sourceLocation}
                  onChange={(e) => setSourceLocation(e.target.value)}
                  className="w-full h-9 rounded-lg bg-surface-100 border border-border px-3 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-primary font-mono"
                />
              </div>
            </>
          ) : (
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Archive File (.zip, .tar.gz)</label>
              <div className="border-2 border-dashed border-border rounded-xl p-6 text-center hover:border-slate-500 transition-colors">
                <Upload className="w-8 h-8 text-slate-400 mx-auto mb-2" />
                <input
                  type="file"
                  accept=".zip,.tar.gz,.tar"
                  onChange={(e) => setUploadFile(e.target.files ? e.target.files[0] : null)}
                  className="text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-surface-100 file:text-slate-200 hover:file:bg-surface-50"
                />
                <p className="text-[11px] text-muted-foreground mt-2">
                  Files are validated and unpacked in secure sandboxed workspace.
                </p>
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-3 border-t border-border">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setIsRegisterModalOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" size="sm" loading={submitting}>
              Register Application
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

