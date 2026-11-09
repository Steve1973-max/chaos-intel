import { describe, it, expect } from 'vitest';
import { NAV_ITEMS, NavigationPage } from '../components/layout/Sidebar';

describe('Navigation & Information Architecture', () => {
  it('contains all 11 required enterprise sidebar sections in correct order', () => {
    const expectedSections: NavigationPage[] = [
      'overview',
      'applications',
      'architecture',
      'risks',
      'testing-agents',
      'test-executions',
      'chaos-experiments',
      'observability',
      'failure-intelligence',
      'reports',
      'settings',
    ];

    expect(NAV_ITEMS.map((item) => item.id)).toEqual(expectedSections);
    expect(NAV_ITEMS.length).toBe(11);
  });

  it('marks chaos-experiments section with dry-run badge', () => {
    const chaosNav = NAV_ITEMS.find((item) => item.id === 'chaos-experiments');
    expect(chaosNav).toBeDefined();
    expect(chaosNav?.badge).toBe('Dry-Run');
  });
});

