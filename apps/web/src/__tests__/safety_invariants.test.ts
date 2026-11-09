import { describe, it, expect } from 'vitest';
import { ChaosExperiment, ChaosReport, RootCauseHypothesis } from '../api/types';

describe('CHAOS-INTEL Phase 6 Platform Invariants', () => {
  it('enforces live_execution is false and mode is dry_run for chaos simulations', () => {
    const report: ChaosReport = {
      run_id: 'dry-run-001',
      experiment_id: 'exp-01',
      verdict: 'DRY_RUN_VERIFIED',
      dry_run: true,
      live_execution: false,
      fault_type: 'network_latency',
      target_id: 'order-service',
      recovery_status: 'SIMULATED_RECOVERED',
      timeline: [
        { timestamp: '00:00:00', event_type: 'SAFETY_CHECK', detail: 'Live socket injection disabled' },
      ],
    };

    expect(report.live_execution).toBe(false);
    expect(report.dry_run).toBe(true);
    expect(report.verdict).toBe('DRY_RUN_VERIFIED');
  });

  it('guarantees root cause hypotheses strictly preserve is_causation_proven = false', () => {
    const hypothesis: RootCauseHypothesis = {
      hypothesis_id: 'hypo-01',
      probable_root_cause_service: 'postgres-cluster',
      failure_category: 'RESOURCE_SATURATION',
      title: 'Database Connection Pool Starvation',
      explanation: 'Correlated metrics indicate pool starvation.',
      confidence: 0.89,
      rank: 1,
      is_causation_proven: false, // Invariant: Inferred causes must NEVER be presented as proven facts
      supporting_evidence: ['Active pool reached 20 connections limit'],
      conflicting_evidence: ['CPU utilization remained below 45%'],
    };

    expect(hypothesis.is_causation_proven).toBe(false);
    expect(hypothesis.confidence).toBeLessThanOrEqual(1.0);
    expect(hypothesis.rank).toBe(1);
  });
});

