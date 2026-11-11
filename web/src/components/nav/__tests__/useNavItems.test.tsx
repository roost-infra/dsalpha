import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { NAV_ITEMS } from '../navItems';
import { useNavItems } from '../useNavItems';

const h = vi.hoisted(() => ({ enabled: new Set<string>() }));
vi.mock('@/plugins/usePagePlugins', () => ({
  usePagePlugins: () => ({ enabled: h.enabled }),
}));

function keys() {
  return renderHook(() => useNavItems()).result.current.map((item) => item.key);
}

beforeEach(() => {
  h.enabled = new Set();
});

describe('the primary nav', () => {
  it('draws the core items', () => {
    expect(keys()).toEqual(NAV_ITEMS.map((item) => item.key));
    expect(keys()).not.toContain('/market');
    expect(keys()).not.toContain('/orders');
  });

  it('appends an enabled page plugin after the core items', () => {
    h.enabled = new Set(['market-center']);
    expect(keys()).toEqual([...NAV_ITEMS.map((item) => item.key), '/p/market']);
  });

  it('removes the plugin entry again when it is disabled', () => {
    h.enabled = new Set(['market-center']);
    expect(keys()).toContain('/p/market');
    h.enabled = new Set();
    expect(keys()).not.toContain('/p/market');
  });
});
