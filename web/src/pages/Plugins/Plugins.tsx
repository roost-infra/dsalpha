import { SectionPage } from './components/shell/SectionPage';
import { PLUGINS_SHELL } from './components/shell/sections';

/**
 * /plugins — "Extensions": what I installed.
 *
 * The sections that extend what the agent can do — plugins, skills, subagents,
 * page plugins — beside the brokerages it signs in with and the vault they read
 * from. A skill or connector enabled here reaches every workspace of the user
 * unless its row is scoped down; connectors themselves are hosted by `/apps`
 * now (see `PLUGINS_SHELL`), and a link that still names them is redirected
 * there by the app shell rather than answered here.
 *
 * The page frame is `SectionPage`'s, shared with `/apps`; this names the shell
 * it draws and nothing else.
 */
function Plugins() {
  return <SectionPage shell={PLUGINS_SHELL} />;
}

export default Plugins;
