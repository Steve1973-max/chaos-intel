import { useState } from 'react';
import { Application } from '@/api/types';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { MetricChart } from '@/components/charts/MetricChart';
import { NavigationPage } from '@/components/layout/Sidebar';
import {
  Activity,
  RefreshCw,
  Search,
  Filter,
  Terminal,
  Cpu,
  Layers,
  Clock,
  Radio,
  AlertCircle,
  FileText,
  GitCommit,
} from 'lucide-react';

interface ObservabilityProps {
  applications: Application[];
  selectedAppId: string | null;
  onSelectApp: (appId: string) => void;
  onNavigate: (page: NavigationPage) => void;
}

export function Observability({
  applications,
  selectedAppId,
  onSelectApp,
  onNavigate,
}: ObservabilityProps) {
  const [timeRange, setTimeRange] = useState('15m');
  const [logFilter, setLogFilter] = useState('ALL');
  const [logSearch, setLogSearch] = useState('');
  const [activeTab, setActiveTab] = useState<'metrics' | 'logs' | 'traces'>('metrics');

  const latencyP95Data = [
    { timestamp: '10:15', value: 38 },
    { timestamp: '10:18', value: 42 },
    { timestamp: '10:21', value: 41 },
    { timestamp: '10:24', value: 95 },
    { timestamp: '10:27', value: 180 },
    { timestamp: '10:30', value: 65 },
    { timestamp: '10:33', value: 43 },
  ];

  const throughputData = [
    { timestamp: '10:15', value: 240 },
    { timestamp: '10:18', value: 255 },
    { timestamp: '10:21', value: 260 },
    { timestamp: '10:24', value: 310 },
    { timestamp: '10:27', value: 290 },
    { timestamp: '10:30', value: 250 },
    { timestamp: '10:33', value: 245 },
  ];

  const cpuData = [
    { timestamp: '10:15', value: 32 },
    { timestamp: '10:18', value: 34 },
    { timestamp: '10:21', value: 33 },
    { timestamp: '10:24', value: 68 },
    { timestamp: '10:27', value: 84 },
    { timestamp: '10:30', value: 45 },
    { timestamp: '10:33', value: 35 },
  ];

  const memoryData = [
    { timestamp: '10:15', value: 58 },
    { timestamp: '10:18', value: 59 },
    { timestamp: '10:21', value: 60 },
    { timestamp: '10:24', value: 72 },
    { timestamp: '10:27', value: 74 },
    { timestamp: '10:30', value: 63 },
    { timestamp: '10:33', value: 61 },
  ];

  const sampleLogs = [
    {
      timestamp: '10:24:12.450',
      level: 'INFO',
      service: 'api-gateway',
      message: 'Incoming HTTP POST /api/v1/orders routing to order-service:8080',
    },
    {
      timestamp: '10:24:12.490',
      level: 'INFO',
      service: 'order-service',
      message: 'Acquiring DB transaction lease for idempotency reservation key ord-9912',
    },
    {
      timestamp: '10:25:01.120',
      level: 'WARN',
      service: 'order-service',
      message: 'Connection pool saturation detected: active=19/20, wait_time_ms=850',
    },
    {
      timestamp: '10:25:02.840',
      level: 'ERROR',
      service: 'payment-adapter',
      message: 'SocketTimeoutException calling external gateway: Read timed out after 2000ms',
    },
    {
      timestamp: '10:25:03.110',
      level: 'INFO',
      service: 'order-service',
      message: 'Circuit breaker tripped to OPEN state for downstream payment-adapter. Executing fallback.',
    },
    {
      timestamp: '10:26:40.900',
      level: 'INFO',
      service: 'api-gateway',
      message: 'Health probe returned 200 OK. Cluster restored to normal latency baseline.',
    },
  ];

  const filteredLogs = sampleLogs.filter((log) => {
    const matchesLevel = logFilter === 'ALL' || log.level === logFilter;
    const matchesSearch =
      !logSearch ||
      log.message.toLowerCase().includes(logSearch.toLowerCase()) ||
      log.service.toLowerCase().includes(logSearch.toLowerCase());
    return matchesLevel && matchesSearch;
  });

  const sampleTraces = [
    {
      span_id: 'span-root-01',
      service: 'api-gateway',
      operation: 'POST /api/v1/orders',
      duration_ms: 1240,
      status: 'error',
      children: [
        {
          span_id: 'span-child-02',
          service: 'order-service',
          operation: 'OrderService.processOrder',
          duration_ms: 1190,
          status: 'error',
          children: [
            {
              span_id: 'span-db-03',
              service: 'postgres-cluster',
              operation: 'SELECT * FROM accounts WHERE id = ? FOR UPDATE',
              duration_ms: 45,
              status: 'ok',
            },
            {
              span_id: 'span-ext-04',
              service: 'payment-adapter',
              operation: 'HTTPS POST /charges',
              duration_ms: 1050,
              status: 'error',
            },
          ],
        },
      ],
    },
  ];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/80">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">Unified Observability Engine</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Distributed tracing, normalized telemetry streams, and structured log exploration.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <div className="flex rounded-lg bg-surface-200 p-0.5 border border-border">
            {['5m', '15m', '1h', '6h'].map((r) => (
              <button
                key={r}
                onClick={() => setTimeRange(r)}
                className={`px-2.5 py-1 text-xs font-mono font-medium rounded-md transition-colors ${
                  timeRange === r ? 'bg-primary text-white shadow-sm' : 'text-slate-400 hover:text-white'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {}}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Live Poll
          </Button>
        </div>
      </div>

      {/* Tabs Switcher: Metrics, Logs, Traces */}
      <div className="flex border-b border-border">
        <button
          onClick={() => setActiveTab('metrics')}
          className={`px-4 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'metrics'
              ? 'border-accent-cyan text-accent-cyan'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Activity className="w-3.5 h-3.5" /> Telemetry Metrics
        </button>
        <button
          onClick={() => setActiveTab('logs')}
          className={`px-4 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'logs'
              ? 'border-accent-cyan text-accent-cyan'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <FileText className="w-3.5 h-3.5" /> Structured Logs
        </button>
        <button
          onClick={() => setActiveTab('traces')}
          className={`px-4 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'traces'
              ? 'border-accent-cyan text-accent-cyan'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <GitCommit className="w-3.5 h-3.5" /> Distributed Traces
        </button>
      </div>

      {/* Metrics View */}
      {activeTab === 'metrics' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <MetricChart
            title="Request Latency (p95)"
            description="End-to-end response latency across all service routes"
            data={latencyP95Data}
            unit="ms"
            color="cyan"
            currentValue="43"
            threshold={150}
          />
          <MetricChart
            title="Throughput Ingress"
            description="Normalized requests per second across cluster"
            data={throughputData}
            unit="req/s"
            color="emerald"
            currentValue="245"
          />
          <MetricChart
            title="CPU Utilization"
            description="Aggregated container compute load"
            data={cpuData}
            unit="%"
            color="amber"
            currentValue="35"
            threshold={80}
          />
          <MetricChart
            title="Memory Resident Set (RSS)"
            description="Total RAM usage across active instances"
            data={memoryData}
            unit="%"
            color="blue"
            currentValue="61"
            threshold={85}
          />
        </div>
      )}

      {/* Logs View */}
      {activeTab === 'logs' && (
        <Card>
          <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border/60 pb-3">
            <div className="flex items-center gap-2 flex-1">
              <div className="relative flex-1 max-w-sm">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Filter logs by message or service..."
                  value={logSearch}
                  onChange={(e) => setLogSearch(e.target.value)}
                  className="w-full h-8 pl-8 pr-3 text-xs rounded-lg bg-surface-100 border border-border text-slate-200 placeholder-slate-500 focus:outline-none focus:border-primary font-mono"
                />
              </div>
              <select
                value={logFilter}
                onChange={(e) => setLogFilter(e.target.value)}
                className="h-8 px-2.5 text-xs rounded-lg bg-surface-100 border border-border text-slate-300 focus:outline-none focus:border-primary font-mono"
              >
                <option value="ALL">All Levels</option>
                <option value="INFO">INFO Only</option>
                <option value="WARN">WARN Only</option>
                <option value="ERROR">ERROR Only</option>
              </select>
            </div>
            <span className="text-xs font-mono text-slate-400">
              Showing {filteredLogs.length} events
            </span>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y divide-border/40 font-mono text-xs">
              {filteredLogs.map((log, idx) => (
                <div
                  key={idx}
                  className="p-2.5 hover:bg-surface-300/40 flex items-start gap-3 transition-colors"
                >
                  <span className="text-slate-500 text-[10px] shrink-0 mt-0.5">{log.timestamp}</span>
                  <span
                    className={`px-1.5 py-0.2 rounded text-[10px] font-bold shrink-0 ${
                      log.level === 'ERROR'
                        ? 'bg-rose-950/80 text-rose-400 border border-rose-800'
                        : log.level === 'WARN'
                        ? 'bg-amber-950/80 text-amber-400 border border-amber-800'
                        : 'bg-surface-100 text-slate-400 border border-border'
                    }`}
                  >
                    {log.level}
                  </span>
                  <span className="text-accent-cyan text-[11px] shrink-0 font-medium">{log.service}:</span>
                  <span className="text-slate-300 text-[11px] break-all">{log.message}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Traces View */}
      {activeTab === 'traces' && (
        <Card>
          <CardHeader className="pb-3 border-b border-border/60">
            <CardTitle className="text-sm">Span Waterfall Explorer</CardTitle>
            <p className="text-xs text-muted-foreground mt-0.5">
              Call hierarchy and duration distribution across distributed microservices.
            </p>
          </CardHeader>
          <CardContent className="p-4 space-y-4">
            {sampleTraces.map((trace) => (
              <div key={trace.span_id} className="space-y-2">
                <div className="p-3 rounded-lg bg-surface-300/80 border border-border/60 space-y-2">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <div className="flex items-center gap-2">
                      <span className="text-accent-cyan font-bold">{trace.service}</span>
                      <span className="text-slate-400">•</span>
                      <span className="text-slate-200">{trace.operation}</span>
                    </div>
                    <span className="text-rose-400 font-bold">{trace.duration_ms} ms</span>
                  </div>

                  {/* Relative duration progress */}
                  <div className="h-2 w-full bg-surface-200 rounded-full overflow-hidden">
                    <div className="h-full bg-rose-500 w-full" />
                  </div>

                  {/* Child spans */}
                  <div className="pl-6 pt-2 space-y-2 border-l border-border/80 ml-2">
                    {trace.children.map((child) => (
                      <div key={child.span_id} className="space-y-1.5">
                        <div className="flex items-center justify-between text-xs font-mono">
                          <div className="flex items-center gap-2">
                            <span className="text-purple-400 font-bold">{child.service}</span>
                            <span className="text-slate-500">•</span>
                            <span className="text-slate-300">{child.operation}</span>
                          </div>
                          <span className="text-rose-400 font-bold">{child.duration_ms} ms</span>
                        </div>
                        <div className="h-1.5 w-full bg-surface-200 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-rose-400"
                            style={{ width: `${(child.duration_ms / trace.duration_ms) * 100}%` }}
                          />
                        </div>

                        {/* Grandchildren */}
                        <div className="pl-6 pt-1 space-y-2 border-l border-border/60 ml-2">
                          {child.children?.map((gc) => (
                            <div key={gc.span_id} className="space-y-1">
                              <div className="flex items-center justify-between text-[11px] font-mono">
                                <div className="flex items-center gap-2">
                                  <span className={gc.status === 'error' ? 'text-rose-400 font-bold' : 'text-emerald-400 font-bold'}>
                                    {gc.service}
                                  </span>
                                  <span className="text-slate-500">•</span>
                                  <span className="text-slate-300">{gc.operation}</span>
                                </div>
                                <span className="text-slate-400">{gc.duration_ms} ms</span>
                              </div>
                              <div className="h-1 w-full bg-surface-200 rounded-full overflow-hidden">
                                <div
                                  className={`h-full ${gc.status === 'error' ? 'bg-rose-500' : 'bg-emerald-500'}`}
                                  style={{ width: `${(gc.duration_ms / trace.duration_ms) * 100}%` }}
                                />
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

