import { SectionPage } from '@/pages/Plugins/components/shell/SectionPage';
import { APPS_SHELL } from '@/pages/Plugins/components/shell/sections';

/**
 * /apps — "Connect": what I linked.
 *
 * The single entry for connecting something to the bots, in two sections:
 * the managed apps (Composio OAuth, no scope) and the connectors (MCP servers,
 * brought with their own key and scoped per workspace). They are two data
 * models and stay two, each keeping its own controls; what this page unifies is
 * the entry point, so "I want to connect X" is one place rather than a guess
 * between this page and a tab of Plugins.
 *
 * The page frame — rail, header, scroll port, section bodies — is
 * `SectionPage`'s, shared with `/plugins`; this names the shell it draws and
 * nothing else.
 */
function Apps() {
  return <SectionPage shell={APPS_SHELL} />;
}

export default Apps;
