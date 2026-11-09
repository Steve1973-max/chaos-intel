import { useEffect, useState } from 'react';
import { Application, TestExecution } from '@/api/types';
import { api } from '@/api/client';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { NavigationPage } from '@/components/layout/Sidebar';
import {
  PlayCircle,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
  ChevronRight,
  Flame,
  Bot,
  Terminal,
  Activity,
} from 'lucide-react';

interface TestExecutionsProps {
  applications: Application[];
  selectedAppId: string | null;
  onSelectApp: (appId: string) => void;
  onNavigate: (page: NavigationPage) => void;
}

export function TestExecutions({
  applications,
  selectedAppId,
  onSelectApp,
  onNavigate,
}: TestExecutionsProps) {
  const [executions, setExecutions] = useState<TestExecution[]>([]);
  const [selectedExecution, setSelectedExecution] = useState<TestExecution | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadExecutions();
  }, [selectedAppId]);

  const loadExecutions = async () => {
    setLoading(true);
    try {
      // Simulate/retrieve latest execution results
      const mockExecs: TestExecution[] = [
        {
          execution_id: 'exec-849201',
          plan_id: 'plan-checkout-01',
          application_id: selectedAppId || 'app-01',
          status: 'passed',
          duration_ms: 1840,
          passed_count: 5,
          failed_count: 0,
          step_results: [
            { step_number: 1, step_name: 'Auth Token Handshake', status: 'passed', duration_ms: 120 },
            { step_number: 2, step_name: 'POST /api/v1/orders - Payload Validation', status: 'passed', duration_ms: 340 },
            { step_number: 3, step_name: 'PostgreSQL Order Row Persistence', status: 'passed', duration_ms: 220 },
            { step_number: 4, step_name: 'Kafka OrderCreated Event Emitted', status: 'passed', duration_ms: 180 },
            { step_number: 5, step_name: 'Idempotency Nonce Replay Fenced', status: 'passed', duration_ms: 980 },
          ],
        },
        {
          execution_id: 'exec-849198',
          plan_id: 'plan-checkout-01',
          application_id: selectedAppId || 'app-01',
          status: 'partial_failure',
          duration_ms: 3420,
          passed_count: 4,
          failed_count: 1,
          step_results: [
            { step_number: 1, step_name: 'Auth Token Handshake', status: 'passed', duration_ms: 110 },
            { step_number: 2, step_name: 'POST /api/v1/orders - Payload Validation', status: 'passed', duration_ms: 290 },
            { step_number: 3, step_name: 'PostgreSQL Order Row Persistence', status: 'passed', duration_ms: 240 },
            {
              step_number: 4,
              step_name: 'Payment Webhook Callback Timeout Check',
              status: 'failed',
              duration_ms: 2500,
              error_message: 'Request timed out after 2000ms SLA without circuit breaker activation.',
            },
            { step_number: 5, step_name: 'Order Compensation Rollback', status: 'passed', duration_ms: 280 },
          ],
        },
      ];

      setExecutions(mockExecs);
      setSelectedExecution(mockExecs[0]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/80">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">Test Executions & Verification</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Step-level test execution results, latency timings, and failure localization.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <Button
            variant="outline"
            size="sm"
            onClick={loadExecutions}
            loading={loading}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Refresh
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => onNavigate('testing-agents')}
            icon={<Bot className="w-3.5 h-3.5" />}
          >
            New Test Plan
          </Button>
        </div>
      </div>

      {/* Main Split: Left Execution Runs, Right Step Inspector */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Execution Runs List */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-3 border-b border-border/60">
            <CardTitle className="text-sm">Execution History</CardTitle>
          </CardHeader>
          <CardContent className="p-0 divide-y divide-border/60">
            {executions.map((exec) => {
              const isSelected = selectedExecution?.execution_id === exec.execution_id;

              return (
                <div
                  key={exec.execution_id}
                  onClick={() => setSelectedExecution(exec)}
                  className={`p-3.5 cursor-pointer transition-colors ${
                    isSelected ? 'bg-primary/10 border-l-2 border-primary' : 'hover:bg-surface-300/60'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-semibold text-slate-200">
                      {exec.execution_id}
                    </span>
                    <Badge
                      variant={
                        exec.status === 'passed'
                          ? 'success'
                          : exec.status === 'failed'
                          ? 'destructive'
                          : 'warning'
                      }
                    >
                      {exec.status}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-slate-400 mt-2">
                    <span className="font-mono">{exec.plan_id}</span>
                    <span className="flex items-center gap-1 font-mono text-slate-300">
                      <Clock className="w-3 h-3 text-slate-500" />
                      {exec.duration_ms} ms
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-[10px] text-slate-500 font-mono mt-1">
                    <span className="text-emerald-400">Passed: {exec.passed_count}</span>
                    <span className="text-slate-600">•</span>
                    <span className={exec.failed_count > 0 ? 'text-rose-400' : 'text-slate-400'}>
                      Failed: {exec.failed_count}
                    </span>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Step-by-Step Execution Detail */}
        <Card className="lg:col-span-2">
          {selectedExecution ? (
            <>
              <CardHeader className="pb-3 border-b border-border/60 flex flex-row items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-sm">Step Execution Details</CardTitle>
                    <Badge variant={selectedExecution.status === 'passed' ? 'success' : 'warning'}>
                      {selectedExecution.status}
                    </Badge>
                  </div>
                  <p className="text-[11px] font-mono text-muted-foreground mt-0.5">
                    Execution ID: {selectedExecution.execution_id} • Duration: {selectedExecution.duration_ms} ms
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onNavigate('failure-intelligence')}
                  icon={<Activity className="w-3.5 h-3.5 text-accent-cyan" />}
                >
                  Correlate Telemetry
                </Button>
              </CardHeader>
              <CardContent className="p-4 space-y-3">
                <div className="space-y-2">
                  {selectedExecution.step_results.map((step) => {
                    const isPassed = step.status === 'passed';

                    return (
                      <div
                        key={step.step_number}
                        className={`p-3 rounded-lg border text-xs transition-colors ${
                          isPassed
                            ? 'bg-surface-300/60 border-border/60'
                            : 'bg-rose-950/20 border-rose-800/80 text-rose-200'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {isPassed ? (
                              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                            ) : (
                              <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
                            )}
                            <span className="font-mono text-slate-400">Step {step.step_number}:</span>
                            <span className="font-semibold text-slate-200">{step.step_name}</span>
                          </div>
                          <span className="font-mono text-[11px] text-slate-400">
                            {step.duration_ms} ms
                          </span>
                        </div>

                        {step.error_message && (
                          <div className="mt-2.5 p-2 rounded bg-surface-400/90 border border-rose-800/60 text-[11px] font-mono text-rose-300 flex items-start gap-2">
                            <Terminal className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
                            <div className="flex-1 overflow-x-auto">{step.error_message}</div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </>
          ) : (
            <CardContent className="py-16 text-center text-xs text-slate-500">
              Select an execution run from the left panel to inspect step traces.
            </CardContent>
          )}
        </Card>
      </div>
    </div>
  );
}

