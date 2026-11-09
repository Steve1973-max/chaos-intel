/**
 * Typed API Client for CHAOS-INTEL Backend Platform.
 */

import {
  Application,
  ArchitectureGraph,
  ChaosExperiment,
  ChaosReport,
  FailureAnalysis,
  HealthStatus,
  PipelineJob,
  RiskAssessment,
  TestExecution,
  TestPlan,
} from './types';

class ApiClient {
  private baseUrl: string;
  private apiKey: string;

  constructor() {
    const hasStorage = typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
    const hasOrigin =
      typeof window !== 'undefined' &&
      typeof window.location !== 'undefined' &&
      Boolean(window.location.origin) &&
      window.location.origin.startsWith('http');
    this.baseUrl =
      (hasStorage && window.localStorage.getItem('chaos_api_url')) ||
      (hasOrigin ? `${window.location.origin}/api/v1` : 'http://127.0.0.1:8000/api/v1');
    this.apiKey = (hasStorage && window.localStorage.getItem('chaos_api_key')) || 'test-operator-key';
  }

  setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/$/, '');
    if (typeof window !== 'undefined' && typeof window.localStorage !== 'undefined') {
      window.localStorage.setItem('chaos_api_url', this.baseUrl);
    }
  }

  setApiKey(key: string) {
    this.apiKey = key;
    if (typeof window !== 'undefined' && typeof window.localStorage !== 'undefined') {
      window.localStorage.setItem('chaos_api_key', key);
    }
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  getApiKey(): string {
    return this.apiKey;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const correlationId = `corr-fe-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;

    const headers: Record<string, string> = {
      'Accept': 'application/json',
      'X-Correlation-ID': correlationId,
      'X-API-Key': this.apiKey,
      ...((options.headers as Record<string, string>) || {}),
    };

    if (!(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }

    try {
      const res = await fetch(url, { ...options, headers });
      if (!res.ok) {
        let errorData: any = {};
        try {
          errorData = await res.json();
        } catch {
          errorData = { message: res.statusText };
        }
        throw new Error(errorData.message || `API Error ${res.status}: ${res.statusText}`);
      }
      return await res.json();
    } catch (err: any) {
      console.warn(`[CHAOS-INTEL API] Request to ${endpoint} failed:`, err.message);
      throw err;
    }
  }

  // --- Health ---
  async getHealth(): Promise<HealthStatus> {
    return this.request<HealthStatus>('/health');
  }

  async getServicesHealth(): Promise<HealthStatus> {
    return this.request<HealthStatus>('/health/services');
  }

  // --- Applications ---
  async getApplications(): Promise<{ items: Application[]; total: number }> {
    return this.request<{ items: Application[]; total: number }>('/applications');
  }

  async getApplication(id: string): Promise<Application> {
    return this.request<Application>(`/applications/${id}`);
  }

  async registerApplication(data: { name: string; source_location: string; source_type?: string }): Promise<Application> {
    return this.request<Application>('/applications/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async uploadArchive(file: File): Promise<Application> {
    const formData = new FormData();
    formData.append('file', file);
    return this.request<Application>('/applications/upload', {
      method: 'POST',
      body: formData,
    });
  }

  async analyzeApplication(id: string): Promise<{ job_id: string; status: string }> {
    return this.request<{ job_id: string; status: string }>(`/applications/${id}/analyze`, {
      method: 'POST',
    });
  }

  async getArchitecture(id: string): Promise<ArchitectureGraph> {
    return this.request<ArchitectureGraph>(`/applications/${id}/architecture`);
  }

  async getRisks(id: string): Promise<RiskAssessment> {
    return this.request<RiskAssessment>(`/applications/${id}/risks`);
  }

  // --- Testing Agents ---
  async generateTestPlan(applicationId: string, options: Record<string, any> = {}): Promise<TestPlan> {
    return this.request<TestPlan>('/testing/plans/generate', {
      method: 'POST',
      body: JSON.stringify({ application_id: applicationId, options }),
    });
  }

  async getTestPlan(planId: string): Promise<TestPlan> {
    return this.request<TestPlan>(`/testing/plans/${planId}`);
  }

  async initiateTestExecution(planId: string, applicationId: string): Promise<TestExecution> {
    return this.request<TestExecution>('/testing/executions', {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId, application_id: applicationId }),
    });
  }

  async getTestExecution(executionId: string): Promise<TestExecution> {
    return this.request<TestExecution>(`/testing/executions/${executionId}`);
  }

  // --- Chaos Experiments ---
  async createChaosExperiment(spec: Partial<ChaosExperiment>): Promise<ChaosExperiment> {
    return this.request<ChaosExperiment>('/chaos/experiments', {
      method: 'POST',
      body: JSON.stringify(spec),
    });
  }

  async approveChaosExperiment(experimentId: string, data: { approved_by: string; grant_id: string }): Promise<any> {
    return this.request<any>(`/chaos/experiments/${experimentId}/approve`, {
      method: 'POST',
      headers: { 'X-API-Key': 'test-admin-key' }, // Admin role required for approval
      body: JSON.stringify(data),
    });
  }

  async initiateChaosExecution(experimentId: string, applicationId: string): Promise<ChaosReport> {
    return this.request<ChaosReport>('/chaos/executions', {
      method: 'POST',
      body: JSON.stringify({ experiment_id: experimentId, application_id: applicationId, dry_run: true }),
    });
  }

  async getChaosExecution(runId: string): Promise<ChaosReport> {
    return this.request<ChaosReport>(`/chaos/executions/${runId}`);
  }

  // --- Telemetry & Failure Intelligence ---
  async analyzeFailure(data: { application_id: string; chaos_report_id?: string }): Promise<FailureAnalysis> {
    return this.request<FailureAnalysis>('/intelligence/analyze', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getAnalysisReport(analysisId: string): Promise<FailureAnalysis> {
    return this.request<FailureAnalysis>(`/intelligence/reports/${analysisId}`);
  }

  async getRecommendations(params?: { target_service?: string; priority?: string }): Promise<{ recommendations: any[] }> {
    const q = new URLSearchParams(params as any).toString();
    return this.request<{ recommendations: any[] }>(`/intelligence/recommendations${q ? `?${q}` : ''}`);
  }

  // --- Distributed Orchestration ---
  async triggerPipeline(data: {
    source_path: string;
    application_name: string;
    idempotency_key?: string;
    approved_by?: string;
  }): Promise<PipelineJob> {
    return this.request<PipelineJob>('/orchestration/pipeline', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getPipelineJob(jobId: string): Promise<PipelineJob> {
    return this.request<PipelineJob>(`/orchestration/pipeline/${jobId}`);
  }

  async cancelPipelineJob(jobId: string): Promise<any> {
    return this.request<any>(`/orchestration/pipeline/${jobId}/cancel`, {
      method: 'POST',
    });
  }

  async listJobs(): Promise<{ items: PipelineJob[]; total: number }> {
    return this.request<{ items: PipelineJob[]; total: number }>('/orchestration/jobs');
  }
}

export const api = new ApiClient();
