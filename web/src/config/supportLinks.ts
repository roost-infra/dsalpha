/**
 * Where a build sends a user who needs more than the app gives them: the plan
 * page of the account portal, the first support address, and the privacy
 * policy. All are deployment configuration, so each is null when the build
 * sets none, and the plan page only exists in platform mode.
 */
import { isPlatformMode } from './hostMode';

/**
 * The account portal's base, from `VITE_PLATFORM_URL`: a path on this origin or
 * an absolute URL, with no trailing slash. Null outside platform mode, where the
 * portal does not exist even if the variable is set.
 */
export const PLATFORM_URL: string | null = isPlatformMode
  ? import.meta.env.VITE_PLATFORM_URL || '/account'
  : null;

/** The Roost Console is the account portal for this build. When set, every
 *  console link opens its root: plans, usage and wallet all live there. */
export const ROOST_CONSOLE_URL: string | null =
  (import.meta.env.VITE_ROOST_CONSOLE_URL as string | undefined) || null;

/** Where each account path lives inside the one-page Roost Console. */
const CONSOLE_SECTIONS: Record<string, string> = {
  plans: 'plans',
  usage: 'products',
  billing: 'billing',
};

/**
 * A per-destination override for a self-hosted account portal whose section
 * anchors differ, e.g. `VITE_ROOST_CONSOLE_PLANS_URL=https://example/plans`.
 * Unset → the section anchor below.
 */
const CONSOLE_SECTION_URLS: Record<string, string | undefined> = {
  plans: import.meta.env.VITE_ROOST_CONSOLE_PLANS_URL as string | undefined,
  usage: import.meta.env.VITE_ROOST_CONSOLE_USAGE_URL as string | undefined,
  billing: import.meta.env.VITE_ROOST_CONSOLE_BILLING_URL as string | undefined,
};

/** A page of the account portal, by its path (`plans`, `integrations`); null
 *  where there is no portal. A build may override one destination outright
 *  through the `VITE_ROOST_CONSOLE_*_URL` variables; the defaults map a path
 *  to its section on the one-page Roost Console (`#plans`, `#products`,
 *  `#billing`), and a path it has no section for opens its root. */
export function consoleUrl(path: string): string | null {
  const override = CONSOLE_SECTION_URLS[path];
  if (override) return override;
  if (ROOST_CONSOLE_URL) {
    const root = ROOST_CONSOLE_URL.replace(/#.*$/, '');
    const section = CONSOLE_SECTIONS[path];
    return section ? `${root.replace(/\/+$/, '')}/#${section}` : root;
  }
  return PLATFORM_URL && `${PLATFORM_URL}/${path}`;
}

export const PLAN_URL: string | null = consoleUrl('plans');

export const INTEGRATIONS_URL: string | null = consoleUrl('integrations');

export const SUPPORT_EMAIL: string | null =
  (import.meta.env.VITE_CONTACT_EMAILS ?? '')
    .split(',')
    .map((email) => email.trim())
    .find(Boolean) ?? null;

/** Where to get the desktop app. The page offers both editions, the hosted one
 *  and the one that connects to a self-hosted server, so one link serves every build. */
export const DESKTOP_DOWNLOAD_URL =
  (import.meta.env.VITE_DESKTOP_DOWNLOAD_URL as string | undefined)
  || 'https://dsalpha.roostbots.com/app';

export const PRIVACY_URL: string | null = import.meta.env.VITE_PRIVACY_URL || null;
