/**
 * TypeScript API contracts matching CHAOS-INTEL Phase 5 backend schemas.
 */

export interface Application {
  application_id: string;
  name: string;
  source_type: 'directory' | 'archive' | 'git';
  source_location: string;
  status: 'registered' | 'analyzing' | 'analyzed' | 'failed';
  registered_at: string;
  services_count: number;
  apis_count: number;
  technologies: string[];
}

export interface GraphNode {
  node_id: string;
  service_id: string;
  name: string;
  node_type: 'frontend' | 'service' | 'database' | 'queue' | 'external';
  metadata?: Record<string, any>;
}

export interface GraphEdge {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: 'calls' | 'reads' | 'writes' | 'depends_on';
  metadata?: Record<string, any>;
}

export interface ArchitectureGraph {
  application_id: string;
  node_count: number;
  edge_count: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface RiskFinding {
  finding_id: string;
  title: string;
  type: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  description: string;
  affected_components: string[];
  confidence: number;
  recommendations: string[];
}

export interface RiskAssessment {
  application_id: string;
  risk_score: number;
  findings_count: number;
  findings: RiskFinding[];
}

export interface TestCase {
  test_case_id: string;
  title: string;
  test_type: string;
  priority: 'critical' | 'high' | 'medium' | 'low';
  target_id: string;
  target_name?: string;
  reason?: string;
  steps_count?: number;
}

export interface TestPlan {
  plan_id: string;
  application_id: string;
  created_at: string;
  test_cases_count: number;
  test_cases: TestCase[];
  coverage_summary: Record<string, any>;
}

export interface TestExecution {
  execution_id: string;
  plan_id: string;
  application_id: string;
  status: 'queued' | 'running' | 'passed' | 'failed' | 'partial_failure' | 'cancelled';
  duration_ms: number;
  passed_count: number;
  failed_count: number;
  step_results: Array<{
    step_number: number;
    step_name: string;
    status: string;
    duration_ms: number;
    error_message?: string;
  }>;
}

export interface ChaosExperiment {
  experiment_id: string;
  name: string;
  application_id: string;
  target_service_id: string;
  fault_type: string;
  environment: string;
  duration_seconds: number;
  status: 'created' | 'validated' | 'approved' | 'rejected';
  requires_approval: boolean;
  parameters: Record<string, any>;
}

export interface ChaosReport {
  run_id: string;
  experiment_id: string;
  verdict: 'DRY_RUN_VERIFIED' | 'QUEUED' | 'unresolved' | 'passed' | 'failed' | 'aborted';
  dry_run: boolean;
  live_execution: boolean;
  fault_type: string;
  target_id: string;
  recovery_status: string;
  timeline: Array<{
    timestamp: string;
    event_type: string;
    detail: string;
  }>;
}

export interface RootCauseHypothesis {
  hypothesis_id: string;
  probable_root_cause_service: string;
  failure_category: string;
  title: string;
  explanation: string;
  confidence: number;
  rank: number;
  is_causation_proven: boolean;
  supporting_evidence: any[];
  conflicting_evidence: any[];
}

export interface ActionableRecommendation {
  recommendation_id: string;
  category: string;
  priority: 'critical' | 'high' | 'medium' | 'low';
  title: string;
  description: string;
  target_service: string;
  confidence: number;
  remediation_steps?: string[];
}

export interface FailureAnalysis {
  analysis_id: string;
  application_id: string;
  correlation_id: string;
  anomalies_count: number;
  probable_root_causes: RootCauseHypothesis[];
  recommendations_count: number;
  recovery_status: string;
}

export interface PipelineStep {
  step: number;
  name: string;
  status: 'COMPLETED' | 'APPROVED' | 'RUNNING' | 'FAILED' | 'PENDING';
  started_at?: string;
  completed_at?: string;
  detail?: string;
}

export interface PipelineJob {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'dead_letter';
  correlation_id: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  result?: {
    pipeline_id: string;
    application_id: string;
    application_name: string;
    status: string;
    timeline: PipelineStep[];
    artifacts: Record<string, any>;
    recommendations: ActionableRecommendation[];
  };
  error?: {
    error_type: string;
    message: string;
  };
}

export interface HealthStatus {
  status: 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY';
  version: string;
  environment: string;
  services: {
    platform_api?: string;
    application_intelligence?: { status: string; mode: string };
    testing_agents?: { status: string; mode: string };
    chaos_engine?: { status: string; mode: string };
    failure_intelligence?: { status: string; mode: string };
    job_queue?: { status: string; type: string; dead_letter_jobs_count: number };
  };
}

