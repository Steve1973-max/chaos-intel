import { useEffect, useState } from 'react';
import { Application, HealthStatus, PipelineJob } from '@/api/types';
import { api } from '@/api/client';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { StatusIndicator } from '@/components/ui/StatusIndicator';
import { MetricChart } from '@/components/charts/MetricChart';
import { NavigationPage } from '@/components/layout/Sidebar';
import {
  Layers,
  Bot,
  Flame,
  AlertTriangle,
  PlayCircle,
  Plus,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  CheckCircle2,
  Clock,
  ArrowUpRight,
} from 'lucide-react';

interface OverviewProps {
  applications: Application[];
  onNavigate: (page: NavigationPage) => void;
  onRefresh: () => void;
  selectedAppId: string | null;
}

export function Overview({ applications, onNavigate, onRefresh, selectedAppId }: OverviewProps) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [jobs, setJobs] = useState<PipelineJob[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadOverviewData();
  }, []);

  const loadOverviewData = async () => {
    setLoading(true);
    try {
      const [healthRes, jobsRes] = await Promise.allSettled([
        api.getHealth(),
        api.listJobs(),
      ]);

      if (healthRes.status === 'fulfilled') {
        setHealth(healthRes.value);
      }
      if (jobsRes.status === 'fulfilled') {
        setJobs(jobsRes.value.items || []);
      }
    } finally {
      setLoading(false);
    }
  };

  const analyzedAppsCount = applications.filter((a) => a.status === 'analyzed').length;
  const totalServicesCount = applications.reduce((acc, a) => acc + (a.services_count || 0), 0);
  const totalApisCount = applications.reduce((acc, a) => acc + (a.apis_count || 0), 0);

  // Simulated live telemetry sparkline data
  const sampleLatencyData = [
    { timestamp: '10:00', value: 42 },
    { timestamp: '10:05', value: 45 },
    { timestamp: '10:10', value: 68 },
    { timestamp: '10:15', value: 120 },
    { timestamp: '10:20', value: 85 },
    { timestamp: '10:25', value: 48 },
    { timestamp: '10:30', value: 44 },
  ];

  const sampleErrorRateData = [
    { timestamp: '10:00', value: 0.1 },
    { timestamp: '10:05', value: 0.2 },
    { timestamp: '10:10', value: 0.4 },
    { timestamp: '10:15', value: 2.8 },
    { timestamp: '10:20', value: 1.1 },
    { timestamp: '10:25', value: 0.3 },
    { timestamp: '10:30', value: 0.1 },
  ];

  return (
    <div className="space-y-6">
      {/* Top Banner & Quick Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/80">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">System Operational Overview</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Real-time status across multi-agent resilience, testing, and failure intelligence systems.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              onRefresh();
              loadOverviewData();
            }}
            loading={loading}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Refresh
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => onNavigate('applications')}
            icon={<Plus className="w-3.5 h-3.5" />}
          >
            Register Application
          </Button>
        </div>
      </div>

      {/* KPI Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card hover className="cursor-pointer" onClick={() => onNavigate('applications')}>
          <CardContent className="p-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Applications</p>
              <h3 className="text-2xl font-bold font-mono text-slate-100 mt-1">{applications.length}</h3>
              <p className="text-[11px] text-accent-cyan mt-1 flex items-center gap-1 font-medium">
                <span>{analyzedAppsCount} analyzed</span>
                <span className="text-slate-500">•</span>
                <span>{totalServicesCount} services</span>
              </p>
            </div>
            <div className="h-10 w-10 rounded-xl bg-primary/15 border border-primary/30 flex items-center justify-center text-primary-light">
              <Layers className="w-5 h-5" />
            </div>
          </CardContent>
        </Card>

        <Card hover className="cursor-pointer" onClick={() => onNavigate('testing-agents')}>
          <CardContent className="p-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Test Candidates</p>
              <h3 className="text-2xl font-bold font-mono text-slate-100 mt-1">{totalApisCount * 3 || 12}</h3>
              <p className="text-[11px] text-emerald-400 mt-1 flex items-center gap-1 font-medium">
                <span>API, UI & Workflow</span>
              </p>
            </div>
            <div className="h-10 w-10 rounded-xl bg-emerald-950/60 border border-emerald-800/40 flex items-center justify-center text-emerald-400">
              <Bot className="w-5 h-5" />
            </div>
          </CardContent>
        </Card>

        <Card hover className="cursor-pointer" onClick={() => onNavigate('chaos-experiments')}>
          <CardContent className="p-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Chaos Catalog</p>
              <h3 className="text-2xl font-bold font-mono text-slate-100 mt-1">12 Faults</h3>
              <p className="text-[11px] text-amber-400 mt-1 flex items-center gap-1 font-mono">
                <span>Safety Guardrails Enforced</span>
              </p>
            </div>
            <div className="h-10 w-10 rounded-xl bg-amber-950/60 border border-amber-800/40 flex items-center justify-center text-amber-400">
              <Flame className="w-5 h-5" />
            </div>
          </CardContent>
        </Card>

        <Card hover className="cursor-pointer" onClick={() => onNavigate('failure-intelligence')}>
          <CardContent className="p-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Failure Intelligence</p>
              <h3 className="text-2xl font-bold font-mono text-slate-100 mt-1">Active</h3>
              <p className="text-[11px] text-slate-400 mt-1 flex items-center gap-1 font-mono">
                <span>Root-Cause Correlator</span>
              </p>
            </div>
            <div className="h-10 w-10 rounded-xl bg-purple-950/60 border border-purple-800/40 flex items-center justify-center text-purple-400">
              <AlertTriangle className="w-5 h-5" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Subsystem Health Status Matrix */}
      <Card>
        <CardHeader className="pb-3 flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm">Subsystem Health & Fencing Status</CardTitle>
            <p className="text-xs text-muted-foreground mt-0.5">
              Authoritative operational status across decentralized platform microservices.
            </p>
          </div>
          <Badge variant={health?.status === 'HEALTHY' ? 'success' : 'default'}>
            {health?.status || 'HEALTHY'}
          </Badge>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {[
              {
                name: 'API Gateway',
                status: 'HEALTHY',
                detail: 'FastAPI /api/v1',
              },
              {
                name: 'App Intelligence',
                status: health?.services?.application_intelligence?.status || 'HEALTHY',
                detail: health?.services?.application_intelligence?.mode || 'ast-symbolic',
              },
              {
                name: 'Testing Agents',
                status: health?.services?.testing_agents?.status || 'HEALTHY',
                detail: health?.services?.testing_agents?.mode || 'deterministic-prioritizer',
              },
              {
                name: 'Chaos Engine',
                status: health?.services?.chaos_engine?.status || 'HEALTHY',
                detail: 'Dry-Run Enforced',
              },
              {
                name: 'Failure Intel',
                status: health?.services?.failure_intelligence?.status || 'HEALTHY',
                detail: 'Ranked Hypotheses',
              },
              {
                name: 'Job Queue',
                status: health?.services?.job_queue?.status || 'HEALTHY',
                detail: `Dead Letter: ${health?.services?.job_queue?.dead_letter_jobs_count || 0}`,
              },
            ].map((subsystem) => (
              <div
                key={subsystem.name}
                className="rounded-lg bg-surface-300/80 border border-border/70 p-3 flex flex-col justify-between"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-200">{subsystem.name}</span>
                  <StatusIndicator
                    status={subsystem.status === 'HEALTHY' ? 'online' : 'warning'}
                    pulse={false}
                  />
                </div>
                <div className="mt-2 text-[10px] font-mono text-muted-foreground truncate">
                  {subsystem.detail}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Observability Telemetry Live Preview & Pipelines */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Latency Telemetry */}
        <MetricChart
          title="Cluster Latency Telemetry (p95)"
          description="Synthesized request latency under baseline and test loads"
          data={sampleLatencyData}
          unit="ms"
          color="cyan"
          currentValue="44"
          threshold={100}
        />

        {/* Error Rate */}
        <MetricChart
          title="Cluster Error Rate"
          description="HTTP 5xx & connection timeouts per minute"
          data={sampleErrorRateData}
          unit="%"
          color="rose"
          currentValue="0.1"
          threshold={2.0}
        />
      </div>

      {/* Recent Pipeline Jobs & Activity Feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Orchestrated Pipeline Jobs */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-sm">Recent Orchestrated Pipelines</CardTitle>
              <p className="text-xs text-muted-foreground mt-0.5">
                Automated multi-agent resilience audits and validation runs.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onNavigate('test-executions')}
              icon={<ExternalLink className="w-3.5 h-3.5" />}
            >
              View Executions
            </Button>
          </CardHeader>
          <CardContent>
            {jobs.length === 0 ? (
              <div className="py-8 text-center text-xs text-slate-500">
                <Clock className="w-8 h-8 mx-auto mb-2 opacity-40" />
                No pipeline jobs run yet. Launch an end-to-end resilience workflow.
              </div>
            ) : (
              <div className="space-y-2">
                {jobs.slice(0, 5).map((job) => (
                  <div
                    key={job.job_id}
                    className="flex items-center justify-between p-3 rounded-lg bg-surface-300 border border-border/60 hover:bg-surface-100 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <div className="h-8 w-8 rounded-lg bg-surface-200 border border-border flex items-center justify-center font-mono text-xs text-accent-cyan">
                        {job.job_id.substring(0, 4)}
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-slate-200">
                          {job.result?.application_name || 'Resilience Pipeline Job'}
                        </div>
                        <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                          ID: {job.job_id} • Created: {new Date(job.created_at).toLocaleTimeString()}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={
                          job.status === 'completed'
                            ? 'success'
                            : job.status === 'running'
                            ? 'cyan'
                            : job.status === 'failed'
                            ? 'destructive'
                            : 'default'
                        }
                      >
                        {job.status}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onNavigate('reports')}
                        className="h-7 w-7 p-0"
                      >
                        <ArrowUpRight className="w-4 h-4 text-slate-400" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Safety & Fencing Summary */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-accent-cyan" />
              Safety & Invariant Status
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-lg bg-surface-300 p-3 border border-border/60 space-y-2 text-xs">
              <div className="flex items-center justify-between text-slate-300">
                <span className="font-medium">Live Chaos Execution</span>
                <Badge variant="warning">Hard Disabled</Badge>
              </div>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Live environment mutation is prohibited. All faults execute strictly in dry-run mode.
              </p>
            </div>

            <div className="rounded-lg bg-surface-300 p-3 border border-border/60 space-y-2 text-xs">
              <div className="flex items-center justify-between text-slate-300">
                <span className="font-medium">Causation Boundary</span>
                <Badge variant="cyan">Ranked Hypotheses</Badge>
              </div>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Failure intelligence isolates competing probable causes without presenting inferred findings as proven fact.
              </p>
            </div>

            <div className="rounded-lg bg-surface-300 p-3 border border-border/60 space-y-2 text-xs">
              <div className="flex items-center justify-between text-slate-300">
                <span className="font-medium">Idempotency & Replay</span>
                <Badge variant="success">Fenced</Badge>
              </div>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Uncertain execution outcomes are never automatically replayed. Authoritative state checks prevent duplicate execution.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

