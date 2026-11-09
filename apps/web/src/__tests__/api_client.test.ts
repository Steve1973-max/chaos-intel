import { describe, it, expect, beforeEach } from 'vitest';
import { api } from '../api/client';

describe('CHAOS-INTEL API Client', () => {
  const store: Record<string, string> = {};

  beforeEach(() => {
    Object.keys(store).forEach((key) => delete store[key]);
    (globalThis as any).window = {
      localStorage: {
        getItem: (k: string) => store[k] || null,
        setItem: (k: string, v: string) => {
          store[k] = v;
        },
        clear: () => {
          Object.keys(store).forEach((key) => delete store[key]);
        },
      },
    };
  });

  it('initializes with default endpoint and operator key', () => {
    expect(api.getBaseUrl()).toBe('http://127.0.0.1:8000/api/v1');
    expect(api.getApiKey()).toBe('test-operator-key');
  });

  it('updates and persists base URL without trailing slash', () => {
    api.setBaseUrl('http://staging.cluster.internal:8080/api/v1/');
    expect(api.getBaseUrl()).toBe('http://staging.cluster.internal:8080/api/v1');
    expect(window.localStorage.getItem('chaos_api_url')).toBe('http://staging.cluster.internal:8080/api/v1');
  });

  it('updates and persists API Key', () => {
    api.setApiKey('admin-key-supersecret');
    expect(api.getApiKey()).toBe('admin-key-supersecret');
    expect(window.localStorage.getItem('chaos_api_key')).toBe('admin-key-supersecret');
  });
});
