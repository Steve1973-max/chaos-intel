import React, { useState, useMemo, useRef } from 'react';
import { ArchitectureGraph as IArchitectureGraph, GraphNode, GraphEdge } from '@/api/types';
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Search,
  Server,
  Database,
  Layers,
  Globe,
  Radio,
  Eye,
  ShieldAlert,
} from 'lucide-react';

interface ArchitectureGraphProps {
  graph: IArchitectureGraph | null;
  selectedNodeId: string | null;
  onSelectNode: (node: GraphNode | null) => void;
  criticalNodeIds?: string[];
}

interface LayoutNode extends GraphNode {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function ArchitectureGraph({
  graph,
  selectedNodeId,
  onSelectNode,
  criticalNodeIds = [],
}: ArchitectureGraphProps) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<string>('all');
  const svgRef = useRef<SVGSVGElement>(null);

  // Layout calculation: organize nodes into intuitive tier layers or circle
  const layoutNodes = useMemo<LayoutNode[]>(() => {
    if (!graph || !graph.nodes || graph.nodes.length === 0) return [];

    // Group nodes by type
    const tiers: Record<string, GraphNode[]> = {
      frontend: [],
      service: [],
      database: [],
      queue: [],
      external: [],
    };

    graph.nodes.forEach((n) => {
      const type = n.node_type || 'service';
      if (tiers[type]) {
        tiers[type].push(n);
      } else {
        tiers.service.push(n);
      }
    });

    const orderedTiers = ['frontend', 'service', 'queue', 'database', 'external'];
    const result: LayoutNode[] = [];
    const tierXSpacing = 280;
    const nodeYSpacing = 110;
    const startX = 80;

    let tierIndex = 0;
    orderedTiers.forEach((tierKey) => {
      const nodesInTier = tiers[tierKey];
      if (nodesInTier.length > 0) {
        const totalHeight = (nodesInTier.length - 1) * nodeYSpacing;
        const startY = Math.max(80, 240 - totalHeight / 2);

        nodesInTier.forEach((node, idx) => {
          result.push({
            ...node,
            x: startX + tierIndex * tierXSpacing,
            y: startY + idx * nodeYSpacing,
            width: 180,
            height: 72,
          });
        });
        tierIndex++;
      }
    });

    return result;
  }, [graph]);

  const nodeMap = useMemo(() => {
    const map = new Map<string, LayoutNode>();
    layoutNodes.forEach((n) => map.set(n.node_id, n));
    return map;
  }, [layoutNodes]);

  // Filtered nodes
  const visibleNodes = useMemo(() => {
    return layoutNodes.filter((node) => {
      const matchesSearch = !searchQuery || node.name.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesType = filterType === 'all' || node.node_type === filterType;
      return matchesSearch && matchesType;
    });
  }, [layoutNodes, searchQuery, filterType]);

  // Edges between layout nodes
  const layoutEdges = useMemo(() => {
    if (!graph || !graph.edges) return [];
    return graph.edges
      .map((edge) => {
        const source = nodeMap.get(edge.source_node_id);
        const target = nodeMap.get(edge.target_node_id);
        if (!source || !target) return null;
        return {
          ...edge,
          source,
          target,
        };
      })
      .filter((e): e is NonNullable<typeof e> => e !== null);
  }, [graph, nodeMap]);

  // Zoom controls
  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 0.15, 2.5));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 0.15, 0.4));
  const handleResetZoom = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  // Pan controls
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.target === svgRef.current || (e.target as HTMLElement).tagName === 'svg') {
      setIsDragging(true);
      setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging) {
      setPan({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
    }
  };

  const handleMouseUp = () => setIsDragging(false);

  // Helper for node type styling
  const getNodeColor = (type: string, isSelected: boolean, isCritical: boolean) => {
    if (isCritical) return 'stroke-amber-400 fill-amber-950/30';
    if (isSelected) return 'stroke-cyan-400 fill-cyan-950/40 ring-2 ring-cyan-500';

    switch (type) {
      case 'frontend':
        return 'stroke-sky-500/80 fill-sky-950/20';
      case 'service':
        return 'stroke-cyan-500/80 fill-cyan-950/20';
      case 'database':
        return 'stroke-emerald-500/80 fill-emerald-950/20';
      case 'queue':
        return 'stroke-purple-500/80 fill-purple-950/20';
      case 'external':
        return 'stroke-slate-500/80 fill-slate-900/40';
      default:
        return 'stroke-slate-600 fill-surface-200';
    }
  };

  const getNodeIcon = (type: string) => {
    switch (type) {
      case 'frontend':
        return <Globe className="w-3.5 h-3.5 text-sky-400" />;
      case 'service':
        return <Server className="w-3.5 h-3.5 text-cyan-400" />;
      case 'database':
        return <Database className="w-3.5 h-3.5 text-emerald-400" />;
      case 'queue':
        return <Radio className="w-3.5 h-3.5 text-purple-400" />;
      case 'external':
        return <Layers className="w-3.5 h-3.5 text-slate-400" />;
      default:
        return <Server className="w-3.5 h-3.5 text-slate-400" />;
    }
  };

  return (
    <div className="relative flex flex-col h-[580px] w-full rounded-xl border border-border bg-surface-300/60 overflow-hidden select-none">
      {/* Top Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 border-b border-border bg-surface-200/80 backdrop-blur-sm z-10">
        <div className="flex items-center gap-2">
          {/* Search */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search components..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-8 pl-8 pr-3 text-xs rounded-lg bg-surface-100 border border-border text-slate-200 placeholder-slate-500 focus:outline-none focus:border-primary w-48"
            />
          </div>

          {/* Type Filter */}
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="h-8 px-2.5 text-xs rounded-lg bg-surface-100 border border-border text-slate-300 focus:outline-none focus:border-primary"
          >
            <option value="all">All Types</option>
            <option value="frontend">Frontend</option>
            <option value="service">Backend Services</option>
            <option value="database">Databases</option>
            <option value="queue">Queues</option>
            <option value="external">External</option>
          </select>
        </div>

        {/* Legend & Zoom Tools */}
        <div className="flex items-center gap-2">
          {/* Legend */}
          <div className="hidden lg:flex items-center gap-3 text-[11px] text-slate-400 mr-2 border-r border-border pr-3">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-sky-400" /> Frontend
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-cyan-400" /> Service
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-400" /> Database
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-purple-400" /> Queue
            </span>
          </div>

          <button
            onClick={handleZoomIn}
            className="p-1.5 rounded-md bg-surface-100 border border-border text-slate-300 hover:text-white hover:bg-surface-50 transition-colors"
            title="Zoom In"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            onClick={handleZoomOut}
            className="p-1.5 rounded-md bg-surface-100 border border-border text-slate-300 hover:text-white hover:bg-surface-50 transition-colors"
            title="Zoom Out"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <button
            onClick={handleResetZoom}
            className="p-1.5 rounded-md bg-surface-100 border border-border text-slate-300 hover:text-white hover:bg-surface-50 transition-colors"
            title="Reset View"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
          <span className="text-xs font-mono text-slate-400 w-12 text-right">{Math.round(zoom * 100)}%</span>
        </div>
      </div>

      {/* SVG Canvas Area */}
      <div
        className="flex-1 relative cursor-grab active:cursor-grabbing overflow-hidden bg-[radial-gradient(#1e2433_1px,transparent_1px)] [background-size:20px_20px]"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      >
        <svg
          ref={svgRef}
          className="w-full h-full"
          style={{ width: '100%', height: '100%' }}
        >
          <defs>
            <marker
              id="arrow-default"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="#475569" />
            </marker>
            <marker
              id="arrow-selected"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="#06b6d4" />
            </marker>
            <marker
              id="arrow-critical"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="#f59e0b" />
            </marker>
          </defs>

          <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
            {/* Edges */}
            {layoutEdges.map((edge) => {
              const sourceX = edge.source.x + edge.source.width;
              const sourceY = edge.source.y + edge.source.height / 2;
              const targetX = edge.target.x;
              const targetY = edge.target.y + edge.target.height / 2;

              const isEdgeHighlighted =
                selectedNodeId === edge.source_node_id || selectedNodeId === edge.target_node_id;
              const isCriticalEdge =
                criticalNodeIds.includes(edge.source_node_id) && criticalNodeIds.includes(edge.target_node_id);

              // Smooth cubic bezier curve
              const dx = (targetX - sourceX) * 0.5;
              const pathData = `M ${sourceX} ${sourceY} C ${sourceX + dx} ${sourceY}, ${targetX - dx} ${targetY}, ${targetX} ${targetY}`;

              return (
                <g key={edge.edge_id} className="transition-all">
                  <path
                    d={pathData}
                    fill="none"
                    stroke={isCriticalEdge ? '#f59e0b' : isEdgeHighlighted ? '#06b6d4' : '#334155'}
                    strokeWidth={isCriticalEdge || isEdgeHighlighted ? 2.5 : 1.5}
                    strokeDasharray={edge.edge_type === 'depends_on' ? '4 3' : undefined}
                    markerEnd={`url(#${isCriticalEdge ? 'arrow-critical' : isEdgeHighlighted ? 'arrow-selected' : 'arrow-default'})`}
                  />
                  {/* Edge Label on hover or highlight */}
                  {(isEdgeHighlighted || isCriticalEdge) && (
                    <text
                      x={(sourceX + targetX) / 2}
                      y={(sourceY + targetY) / 2 - 6}
                      fill="#94a3b8"
                      fontSize="10"
                      fontFamily="monospace"
                      textAnchor="middle"
                    >
                      {edge.edge_type}
                    </text>
                  )}
                </g>
              );
            })}

            {/* Nodes */}
            {visibleNodes.map((node) => {
              const isSelected = selectedNodeId === node.node_id;
              const isCritical = criticalNodeIds.includes(node.node_id);

              return (
                <g
                  key={node.node_id}
                  transform={`translate(${node.x}, ${node.y})`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectNode(isSelected ? null : node);
                  }}
                  className="cursor-pointer transition-transform duration-100 hover:scale-[1.02]"
                >
                  <rect
                    width={node.width}
                    height={node.height}
                    rx={8}
                    className={`stroke-[1.5] transition-all shadow-md ${getNodeColor(
                      node.node_type,
                      isSelected,
                      isCritical
                    )}`}
                  />

                  {/* Header with Icon and Type */}
                  <g transform="translate(10, 16)">
                    {getNodeIcon(node.node_type)}
                    <text
                      x={20}
                      y={10}
                      fill="#94a3b8"
                      fontSize="10"
                      fontFamily="monospace"
                      className="uppercase font-semibold tracking-wider"
                    >
                      {node.node_type}
                    </text>
                    {isCritical && (
                      <g transform="translate(140, -4)">
                        <ShieldAlert className="w-4 h-4 text-amber-400" />
                      </g>
                    )}
                  </g>

                  {/* Node Name */}
                  <text
                    x={12}
                    y={48}
                    fill={isSelected ? '#ffffff' : '#e2e8f0'}
                    fontSize="12"
                    fontWeight="600"
                    className="truncate"
                  >
                    {node.name.length > 20 ? node.name.substring(0, 18) + '...' : node.name}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>

        {(!graph || graph.nodes.length === 0) && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500">
            <Server className="w-10 h-10 mb-2 opacity-40" />
            <p className="text-sm">No architecture graph available.</p>
            <p className="text-xs text-slate-600 mt-1">Select an application or trigger analysis to inspect topology.</p>
          </div>
        )}
      </div>
    </div>
  );
}

