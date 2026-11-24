/**
 * The page-header Add menu's intent, carried in the URL (`?tab=mcp&add=server`)
 * rather than in page state.
 *
 * The tab bodies are conditionally rendered, so switching tabs unmounts the
 * list that was asked to open a modal; a signal held in page state replayed on
 * every remount, re-opening a modal the user had already closed. As a URL
 * param the intent is stripped by the list that acts on it, which makes it
 * naturally single-shot, and it survives a reload the way a deep link should.
 *
 * An intent names two things, not one: the tab whose list owns the modal, and
 * the page that hosts that tab. They were one value while every section lived
 * on `/plugins`; splitting them is what lets an intent that opens a connector's
 * drawer send the user to `/apps`, and stops a page being handed a tab it does
 * not render.
 */

export type AddIntent =
  | 'plugin'
  | 'server'
  | 'import'
  | 'hithink'
  | 'skill'
  | 'subagent'
  | 'subagent-chat';

export const ADD_PARAM = 'add';

const INTENTS: ReadonlySet<string> = new Set<AddIntent>([
  'plugin',
  'server',
  'import',
  'hithink',
  'skill',
  'subagent',
  'subagent-chat',
]);

/** The page that owns each intent's modal. */
export const ADD_INTENT_PAGE: Record<AddIntent, '/apps' | '/plugins'> = {
  plugin: '/plugins',
  server: '/apps',
  import: '/apps',
  hithink: '/apps',
  skill: '/plugins',
  subagent: '/plugins',
  'subagent-chat': '/plugins',
};

/** The tab inside that page. */
export const ADD_INTENT_TAB: Record<AddIntent, string> = {
  plugin: 'plugins',
  server: 'mcp',
  import: 'mcp',
  hithink: 'mcp',
  skill: 'skills',
  subagent: 'subagents',
  'subagent-chat': 'subagents',
};

/** Where an intent's modal lives, as a URL a page can be sent to. */
export function addIntentHref(intent: AddIntent): string {
  return `${ADD_INTENT_PAGE[intent]}?tab=${ADD_INTENT_TAB[intent]}&${ADD_PARAM}=${intent}`;
}

export function parseAddIntent(params: URLSearchParams): AddIntent | null {
  const raw = params.get(ADD_PARAM);
  return raw && INTENTS.has(raw) ? (raw as AddIntent) : null;
}
