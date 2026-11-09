import { GraphNode, ArchitectureGraph, RiskAssessment } from '@/api/types';
import { Badge } from '@/components/ui/Badge';
import {
  X,
  Server,
  ArrowRight,
  ArrowLeft,
  ShieldAlert,
  Code2,
  Cpu,
} from 'lucide-react';

interface NodeDetailDrawerProps {
  node: GraphNode | null;
  graph: ArchitectureGraph | null;
  risks: RiskAssessment | null;
  onClose: () => void;
  onSelectRelatedNode: (nodeId: string) => void;
}

export function NodeDetailDrawer({
  node,
  graph,
  risks,
  onClose,
  onSelectRelatedNode,
}: NodeDetailDrawerProps) {
  if (!node) return null;

  // Inbound edges (components that call or depend on this node)
  const inboundEdges = graph?.edges.filter((e) => e.target_node_id === node.node_id) || [];
  // Outbound edges (components this node calls or depends on)
  const outboundEdges = graph?.edges.filter((e) => e.source_node_id === node.node_id) || [];

  const getNodeName = (id: string) => {
    const found = graph?.nodes.find((n) => n.node_id === id);
    return found ? found.name : id;
  };

  // Associated risk findings for this component
  const relatedRisks =
    risks?.findings.filter((f) =>
      f.affected_components.some(
        (c) =>
          c.toLowerCase().includes(node.name.toLowerCase()) ||
          c.toLowerCase().includes(node.service_id.toLowerCase())
      )
    ) || [];

  return (
    <div className="w-80 md:w-96 rounded-xl border border-border bg-surface-200/95 backdrop-blur-md p-5 shadow-2xl flex flex-col gap-4 max-h-[580px] overflow-y-auto z-20">
      {/* Header */}
      <div className="flex items-start justify-between pb-3 border-b border-border">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-accent-cyan" />
            <h4 className="text-sm font-bold text-slate-100">{node.name}</h4>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="cyan">{node.node_type}</Badge>
            <span className="text-[11px] font-mono text-slate-400 truncate max-w-[150px]">
              {node.service_id}
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="rounded-lg p-1 text-slate-400 hover:text-white hover:bg-surface-100 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Metadata Section */}
      {node.metadata && Object.keys(node.metadata).length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300">
            <Cpu className="w-3.5 h-3.5 text-slate-400" />
            <span>Component Metadata</span>
          </div>
          <div className="rounded-lg bg-surface-300/80 p-2.5 text-[11px] font-mono space-y-1 border border-border/60">
            {Object.entries(node.metadata).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <span className="text-slate-500">{k}:</span>
                <span className="text-slate-300 truncate max-w-[160px]">{String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Dependencies Section */}
      <div className="space-y-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300">
          <Code2 className="w-3.5 h-3.5 text-slate-400" />
          <span>Interactions & Topology</span>
        </div>

        {/* Downstream (Outbound) */}
        <div>
          <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1 mb-1.5">
            <ArrowRight className="w-3 h-3 text-cyan-400" />
            Downstream Dependencies ({outboundEdges.length})
          </span>
          {outboundEdges.length === 0 ? (
            <div className="text-[11px] text-slate-500 italic pl-4">No downstream calls</div>
          ) : (
            <div className="space-y-1">
              {outboundEdges.map((e) => (
                <button
                  key={e.edge_id}
                  onClick={() => onSelectRelatedNode(e.target_node_id)}
                  className="w-full text-left px-2.5 py-1.5 rounded-md bg-surface-300/60 hover:bg-surface-100 border border-border/40 text-[11px] text-slate-300 flex items-center justify-between transition-colors"
                >
                  <span className="font-medium text-slate-200">{getNodeName(e.target_node_id)}</span>
                  <span className="text-[10px] text-slate-500 font-mono">{e.edge_type}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Upstream (Inbound) */}
        <div>
          <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1 mb-1.5">
            <ArrowLeft className="w-3 h-3 text-purple-400" />
            Upstream Callers ({inboundEdges.length})
          </span>
          {inboundEdges.length === 0 ? (
            <div className="text-[11px] text-slate-500 italic pl-4">No callers registered</div>
          ) : (
            <div className="space-y-1">
              {inboundEdges.map((e) => (
                <button
                  key={e.edge_id}
                  onClick={() => onSelectRelatedNode(e.source_node_id)}
                  className="w-full text-left px-2.5 py-1.5 rounded-md bg-surface-300/60 hover:bg-surface-100 border border-border/40 text-[11px] text-slate-300 flex items-center justify-between transition-colors"
                >
                  <span className="font-medium text-slate-200">{getNodeName(e.source_node_id)}</span>
                  <span className="text-[10px] text-slate-500 font-mono">{e.edge_type}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Associated Risks */}
      <div className="space-y-2 border-t border-border pt-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300">
          <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
          <span>Associated Risks ({relatedRisks.length})</span>
        </div>

        {relatedRisks.length === 0 ? (
          <div className="text-[11px] text-emerald-400 flex items-center gap-1">
            <span>✓ No critical risks identified for this component</span>
          </div>
        ) : (
          <div className="space-y-1.5">
            {relatedRisks.map((risk) => (
              <div
                key={risk.finding_id}
                className="p-2 rounded-lg bg-surface-300 border border-border/60 text-[11px] space-y-1"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-200 truncate">{risk.title}</span>
                  <Badge
                    variant={risk.severity === 'critical' || risk.severity === 'high' ? 'destructive' : 'warning'}
                  >
                    {risk.severity}
                  </Badge>
                </div>
                <p className="text-slate-400 text-[10px] line-clamp-2">{risk.description}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

