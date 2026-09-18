import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../../../shared/api/client';
import StatusPage from './StatusPage';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('shows discovery gaps separately from healthy indexing with original freshness', async () => {
  vi.spyOn(api, 'getChains').mockResolvedValue({ chains: {}, count: 0 });
  vi.spyOn(api, 'getHealth').mockResolvedValue({ count: 1, chains: [{
    chain_id: 1, network_name: 'ethereum', name: 'Ethereum', short_name: 'ETH', health: 'ok', indexed: true, block_lag: 0, reorg_count: 0,
    discovery: { status: 'partial', known_factory_count: 2, last_attempt_at: 1789646500, last_success_at: 1789646400,
      last_error: 'Registry lookup failed', problems: [{ factory_address: '0x0000000000000000000000000000000000000abc', code: 'unsupported_version', version: '9.9.9' }] },
  }] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><StatusPage /></MemoryRouter></QueryClientProvider>);
  expect((await screen.findAllByText('Partial · 2 factories')).length).toBeGreaterThan(0);
  expect(screen.getAllByText('Registry lookup failed').length).toBeGreaterThan(0);
  expect(screen.getAllByText(/Unsupported version \(9.9.9\)/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/Checked /).length).toBeGreaterThan(0);
  expect(screen.getAllByText('Healthy').length).toBeGreaterThan(0);
  client.clear();
});
