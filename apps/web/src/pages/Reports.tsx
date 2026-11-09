import { useEffect, useState } from 'react';
import { Application, HealthStatus } from '@/api/types';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { NavigationPage } from '@/components/layout/Sidebar';
import {
  FileText,
  Download,
  Share2,
  CheckCircle2,
  Printer,
  ShieldCheck,
  Bot,
  Flame,
  AlertTriangle,
  Network,
  Cpu,
} from 'lucide-react';

interface ReportsProps {
  applications: Application[];
  selectedAppId: string | null;
  onSelectApp: (appId: string) => void;
  onNavigate: (page: NavigationPage) => void;
}

export function Reports({ applications, selectedAppId, onSelectApp, onNavigate }: ReportsProps) {
  const currentApp = applications.find((a) => a.application_id === selectedAppId) || applications[0];

  const handleExportJSON = () => {
    const reportData = {
      report_id: `rep-chaos-intel-${Date.now()}`,
      generated_at: new Date().toISOString(),
      application: currentApp || { name: 'Demo Application', application_id: 'app-01' },
      platform_version: '2.4.0',
      summary: {
        architecture_components: 5,
        risk_score: 74,
        test_cases_verified: 5,
        chaos_dry_run_verdict: 'DRY_RUN_VERIFIED',
        hypotheses_identified: 2,
        actionable_recommendations: 2,
      },
      safety_invariants: {
        live_chaos_execution: 'HARD_DISABLED',
        causation_proven: false,
        idempotency_fencing: 'ENFORCED',
      },
    };

    const blob = new Blob([JSON.stringify(reportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chaos-intel-audit-${currentApp?.name || 'app'}-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/80">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">Multi-Agent Resilience Audit Report</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Consolidated intelligence findings across topology, static risk, autonomous testing, and dry-run chaos simulations.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <Button
            variant="outline"
            size="sm"
            onClick={handleExportJSON}
            icon={<Download className="w-3.5 h-3.5" />}
          >
            Export JSON
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handlePrint}
            icon={<Printer className="w-3.5 h-3.5" />}
          >
            Print / Save PDF
          </Button>
        </div>
      </div>

      {/* Main Consolidated Report Document */}
      <Card className="p-2 sm:p-6 bg-surface-200/90 border-border">
        {/* Document Header */}
        <div className="pb-6 border-b border-border/60 flex flex-col sm:flex-row justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs uppercase tracking-widest text-accent-cyan font-bold">
                CHAOS-INTEL AUDIT REPORT
              </span>
              <Badge variant="cyan">Confidential</Badge>
            </div>
            <h2 className="text-2xl font-bold text-slate-100 mt-2">
              {currentApp?.name || 'checkout-service'} - Resilience Evaluation
            </h2>
            <p className="text-xs text-muted-foreground font-mono mt-1">
              Application ID: {currentApp?.application_id || 'app-01'} • Generated: {new Date().toUTCString()}
            </p>
          </div>

          <div className="text-right sm:border-l sm:border-border sm:pl-6">
            <span className="text-[11px] uppercase font-semibold text-muted-foreground">
              Overall Resilience Verdict
            </span>
            <div className="text-xl font-bold font-mono text-amber-400 mt-1">
              CONDITIONAL_PASS
            </div>
            <span className="text-[10px] text-slate-500 font-mono">2 high-priority remediations</span>
          </div>
        </div>

        {/* Section 1: Architecture Topology Summary */}
        <div className="py-6 border-b border-border/60 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Network className="w-4 h-4 text-accent-cyan" />
            <span>1. Architecture & Dependency Profile</span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            The target codebase consists of 5 microservice entities across frontend, business logic, persistence, and event message buses.
            Detected technologies include FastAPI, PostgreSQL, Kafka, and Redis.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
            <div className="p-3 rounded-lg bg-surface-300 border border-border/50 text-xs">
              <span className="text-slate-400 text-[10px] uppercase">Services</span>
              <div className="font-mono font-bold text-slate-200 text-base mt-0.5">5 Detected</div>
            </div>
            <div className="p-3 rounded-lg bg-surface-300 border border-border/50 text-xs">
              <span className="text-slate-400 text-[10px] uppercase">API Routes</span>
              <div className="font-mono font-bold text-slate-200 text-base mt-0.5">14 Cataloged</div>
            </div>
            <div className="p-3 rounded-lg bg-surface-300 border border-border/50 text-xs">
              <span className="text-slate-400 text-[10px] uppercase">Cyclic Calls</span>
              <div className="font-mono font-bold text-emerald-400 text-base mt-0.5">0 (Clean DAG)</div>
            </div>
            <div className="p-3 rounded-lg bg-surface-300 border border-border/50 text-xs">
              <span className="text-slate-400 text-[10px] uppercase">Critical Paths</span>
              <div className="font-mono font-bold text-amber-400 text-base mt-0.5">1 Bottleneck</div>
            </div>
          </div>
        </div>

        {/* Section 2: Vulnerability & Static Risk Findings */}
        <div className="py-6 border-b border-border/60 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <span>2. Risk Vulnerability Assessment</span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Composite risk score stands at <strong className="text-amber-400 font-mono">74 / 100</strong>. Primary vulnerability relates to single-replica database dependencies without read-replica failover or aggressive thread pool fences.
          </p>
          <div className="rounded-lg bg-surface-300/80 p-3 border border-border/60 space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-200">
                Single Point of Failure: Order PostgreSQL Cluster
              </span>
              <Badge variant="destructive">Critical Severity</Badge>
            </div>
            <p className="text-[11px] text-slate-400">
              Database connection pool lacks circuit-breaker fencing. A sudden traffic spike could exhaust connections, cascading timeouts into upstream API gateways.
            </p>
          </div>
        </div>

        {/* Section 3: Autonomous Testing Verification */}
        <div className="py-6 border-b border-border/60 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Bot className="w-4 h-4 text-emerald-400" />
            <span>3. Autonomous Test Suite Execution</span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Testing Agents automatically synthesized and executed 5 targeted API, UI, and workflow test cases.
            All 5 test cases completed successfully with full step-level trace validation.
          </p>
          <div className="rounded-lg bg-surface-300 p-3 border border-border/60 space-y-1.5 text-xs font-mono">
            <div className="flex justify-between text-slate-300">
              <span>Test Suite Execution ID:</span>
              <span className="text-accent-cyan">exec-849201</span>
            </div>
            <div className="flex justify-between text-slate-300">
              <span>Duration:</span>
              <span>1840 ms</span>
            </div>
            <div className="flex justify-between text-slate-300">
              <span>Test Cases:</span>
              <span className="text-emerald-400">5 Passed / 0 Failed</span>
            </div>
          </div>
        </div>

        {/* Section 4: Controlled Chaos Dry-Run Simulation */}
        <div className="py-6 border-b border-border/60 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Flame className="w-4 h-4 text-rose-400" />
            <span>4. Controlled Chaos Simulation (Dry-Run Mode)</span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            A dry-run simulation of <strong className="text-slate-200">Network Latency (800ms)</strong> against <code className="text-accent-cyan font-mono">order-service</code> was verified.
            Live cluster mutation was prohibited by the safety manager. The simulated blast-radius predicted downstream graceful fallback activation within 15 seconds.
          </p>
        </div>

        {/* Section 5: Actionable Remediation Plan */}
        <div className="pt-6 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <CheckCircle2 className="w-4 h-4 text-accent-cyan" />
            <span>5. Recommended Actions for Production Hardening</span>
          </div>
          <div className="space-y-2 text-xs">
            <div className="p-3 rounded-lg bg-surface-300 border border-border/60 flex items-start gap-3">
              <span className="font-mono font-bold text-accent-cyan">01</span>
              <div>
                <h5 className="font-semibold text-slate-200">Scale Connection Pool & Configure Circuit Breaker</h5>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  Increase HikariCP maximum pool size to 50 connections and add a 250ms fail-fast timeout limit.
                </p>
              </div>
            </div>
            <div className="p-3 rounded-lg bg-surface-300 border border-border/60 flex items-start gap-3">
              <span className="font-mono font-bold text-accent-cyan">02</span>
              <div>
                <h5 className="font-semibold text-slate-200">Enforce Webhook Socket Timeout Thresholds</h5>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  Set 800ms socket read timeout on external payment gateways to protect thread pools from upstream degradation.
                </p>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}

