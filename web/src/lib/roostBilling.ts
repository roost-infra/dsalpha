import { api } from '@/api/client';

export interface RoostBilling {
  enabled: boolean;
  available: boolean;
  plan?: string | null;
  access_tier?: number | null;
  remaining_credits?: number | null;
  credit_limit?: number | null;
  used_credits?: number | null;
  allowed?: boolean | null;
}

/** The caller's shared Roost wallet, proxied by the backend from Console. */
export async function getRoostBilling(): Promise<RoostBilling> {
  const { data } = await api.get('/api/v1/billing/roost');
  return data as RoostBilling;
}
