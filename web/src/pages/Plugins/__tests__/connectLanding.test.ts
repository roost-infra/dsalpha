/**
 * Where a connect's answer is said once it lands.
 *
 * A sign-in slower than its flow's state lives comes back to the bare Plugins
 * page, since the server's record of where to return went with the state.
 * The connect's own record kept it, so the failure is said where the connect
 * started rather than dropping the user out of what they were doing.
 */
import { beforeEach, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import type { TFunction } from 'i18next';

vi.mock('@/components/ui/use-toast', () => ({ toast: vi.fn() }));

const { markConnectLeft, rememberConnect } = await import('../connectReturn');
const { landConnectReturn } = await import('../connectLanding');
const { useWelcomeLanding } = await import('../hooks/useConnectLanding');

const t = ((key: string) => key) as unknown as TFunction;
const WELCOME = '/welcome?step=brokerage';

beforeEach(() => {
  sessionStorage.clear();
});

it('says an expired sign-in on the welcome flow it started from', () => {
  window.history.replaceState({}, '', WELCOME);
  rememberConnect({
    server: 'ibkr',
    label: 'Interactive Brokers',
    retry: { kind: 'other' },
    desktopOnly: false,
    returnTo: WELCOME,
  });
  markConnectLeft('ibkr');

  window.history.replaceState({}, '', '/plugins?mcp_error=invalid_state');
  const navigate = vi.fn();
  landConnectReturn({ t, navigate });

  expect(navigate).toHaveBeenCalledWith(WELCOME, { replace: true });
  const { result } = renderHook(() => useWelcomeLanding());
  expect(result.current).toMatchObject({
    owner: 'welcome',
    server: 'ibkr',
    outcome: 'failed',
    reasonKey: 'plugins.oauth.callbackError.invalid_state',
  });
});

it("takes a connect an older build's onboarding sheet sent out on to the welcome flow", () => {
  const LEGACY = '/dashboard?onboarding=connect';
  window.history.replaceState({}, '', LEGACY);
  rememberConnect({
    server: 'ibkr',
    label: 'Interactive Brokers',
    retry: { kind: 'other' },
    desktopOnly: false,
    returnTo: LEGACY,
  });
  markConnectLeft('ibkr');

  window.history.replaceState({}, '', '/plugins?mcp_error=invalid_state');
  const navigate = vi.fn();
  landConnectReturn({ t, navigate });

  expect(navigate).toHaveBeenCalledWith(WELCOME, { replace: true });
  const { result } = renderHook(() => useWelcomeLanding());
  expect(result.current).toMatchObject({ owner: 'welcome', server: 'ibkr', outcome: 'failed' });
});

it('forgets a landing and the connects this tab sent out when the account changes', async () => {
  const { runAuthResets } = await import('@/lib/authResets');
  const { setConnectLanding } = await import('../hooks/useConnectLanding');
  rememberConnect({
    server: 'acme',
    label: 'Acme',
    retry: { kind: 'other' },
    desktopOnly: false,
    returnTo: null,
  });
  setConnectLanding({ owner: 'welcome', server: 'acme', outcome: 'failed', reasonKey: null });
  const { result, rerender } = renderHook(() => useWelcomeLanding());
  expect(result.current).not.toBeNull();

  runAuthResets();
  rerender();

  expect(result.current).toBeNull();
  expect(sessionStorage.getItem('mcp:connect-started')).toBeNull();
});

/**
 * "Try again" reopens the form of the attempt the toast is about.
 *
 * A toast outlives a route change — it sits there while the user moves on. The
 * retry used to read the location at click time, so a user who drifted to
 * another section pressed "Try again" and got the form opened on the section
 * they had wandered to, with that section's params, rather than the one their
 * failed sign-in belonged to. The context belongs to the moment the toast
 * appeared.
 */
it('reopens the failed attempt where it started, not where the user drifted to', async () => {
  const { toast } = await import('@/components/ui/use-toast');

  // The connect left from the connectors section of /apps.
  window.history.replaceState({}, '', '/apps?tab=mcp');
  rememberConnect({
    server: 'acme',
    label: 'Acme',
    retry: { kind: 'server', server: { name: 'acme', transport: 'http' } },
    desktopOnly: false,
    returnTo: '/apps?tab=mcp',
  });
  markConnectLeft('acme');

  window.history.replaceState({}, '', '/apps?tab=mcp&q=foo');
  const navigate = vi.fn();
  landConnectReturn({ t, navigate });

  // The toast carries the action; nothing has navigated yet.
  const call = vi.mocked(toast).mock.calls.at(-1)![0] as { action?: { props: { onClick: () => void } } };
  expect(call.action).toBeDefined();

  // The user wanders to another page before pressing it.
  window.history.replaceState({}, '', '/plugins?tab=skills&q=earnings');

  call.action!.props.onClick();

  // The original section, not `tab=skills`.
  expect(navigate).toHaveBeenCalledWith('/apps?tab=mcp&q=foo', { replace: false });
});
