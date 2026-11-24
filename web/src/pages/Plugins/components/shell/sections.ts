import type { ComponentType } from 'react';
import { AppWindow, FilePlus, KeyRound, Landmark, LayoutTemplate, MessageSquarePlus, Package, Plug, SquareSlash } from 'lucide-react';
import { SubagentsRings } from '@/components/ui/subagents-rings';
import type { AddIntent } from '../../utils/addParam';
import { DETAIL_KIND_TAB, parseDetail, readView, type SectionView } from '../../utils/detailParam';
import { APPS_PATH, PLUGINS_PATH, normalizeSection } from '../../utils/routes';

/**
 * The sections of the two container pages, keyed by the `?tab=` values links
 * already carry.
 *
 * One vocabulary for both pages, and each page shows the slice it hosts:
 * `/apps` ("Connect") holds the managed apps and the connectors, `/plugins`
 * ("Extensions") holds what the agent can use — most with a Yours and a
 * Discover view — and what it signs in with. Which slice belongs to which page
 * is the page shell below, the single place that decides it, so a link, a
 * redirect and an OAuth return cannot disagree about where a section lives.
 */
export type Section =
  | 'apps'
  | 'pages'
  | 'plugins'
  | 'mcp'
  | 'skills'
  | 'subagents'
  | 'brokerages'
  | 'secrets';

/**
 * A group of sections in a page's rail, in the order it draws them.
 *
 * A null `labelKey` means the rail has no heading: `/apps` lists two sections
 * under a page title that already names them, and a heading above each would
 * restate the rail rather than navigate it.
 */
export interface RailGroup {
  labelKey: string | null;
  sections: readonly Section[];
}

/**
 * Everything a page's own navigation and header are read from.
 *
 * One value per page so the container takes its whole shape from one argument:
 * which sections it hosts (and so which `?tab=` it answers to), how its rail is
 * grouped, and where it keeps the user's place. The three are read together and
 * would drift if they lived apart — a section in `sections` that no group lists
 * is one no link can reach.
 */
export interface PageShell {
  /** The page's path; also how a location is matched to its shell. */
  path: string;
  /** The sections this page renders, in the order its rail lists them. */
  sections: readonly Section[];
  /**
   * The section the page opens on when the URL names none.
   *
   * Named rather than taken as `sections[0]`, because the rail's first entry
   * and the page's default are not the same thing: `/plugins` lists the page
   * plugins first but has always opened on Plugins, which is what its own nav
   * item (a bare `/plugins`) lands on.
   */
  defaultSection: Section;
  groups: readonly RailGroup[];
  /** The rail's accessible name. Per page, because a screen reader hears it
   *  where the page title is not read again: the Extensions rail is not the
   *  Connect one. */
  railLabelKey: string;
  /** Per-page scroll memory: the same section keeps its place on each page. */
  scrollKey: string;
}

/** `/plugins` — "Extensions": what the agent can use, and what it signs in
 *  with. `mcp` is absent on purpose: the connectors section is hosted by
 *  `/apps` now, so `/plugins` answers a link that names it with a redirect
 *  rather than a section. */
export const PLUGINS_SHELL: PageShell = {
  path: PLUGINS_PATH,
  sections: ['pages', 'plugins', 'skills', 'subagents', 'brokerages', 'secrets'],
  defaultSection: 'plugins',
  groups: [
    { labelKey: 'plugins.shell.group.pages', sections: ['pages'] },
    { labelKey: 'plugins.shell.group.customize', sections: ['plugins', 'skills', 'subagents'] },
    { labelKey: 'plugins.shell.group.accounts', sections: ['secrets'] },
  ],
  railLabelKey: 'plugins.shell.railLabel',
  scrollKey: 'page:plugins',
};

/** `/apps` — "Connect": what I linked, managed apps beside connectors. One
 *  flat group: two sections and nothing between them, so a heading would only
 *  restate the rail. */
export const APPS_SHELL: PageShell = {
  path: APPS_PATH,
  sections: ['apps', 'mcp'],
  defaultSection: 'apps',
  groups: [{ labelKey: null, sections: ['apps', 'mcp'] }],
  railLabelKey: 'apps.shell.railLabel',
  scrollKey: 'page:apps',
};

/** The shell that owns `pathname`, by its first segment. Anything that is not
 *  `/apps` reads as the Plugins shell, which is the page every other caller is
 *  on. */
export function shellFor(pathname: string): PageShell {
  return pathname.split('/')[1] === APPS_PATH.slice(1) ? APPS_SHELL : PLUGINS_SHELL;
}

// Bare literals (not a template) so the locale parity test sees every label.
export const SECTION_LABEL_KEYS: Record<Section, string> = {
  apps: 'apps.shell.section.apps',
  pages: 'plugins.shell.section.pages',
  plugins: 'plugins.shell.section.plugins',
  mcp: 'plugins.shell.section.mcp',
  skills: 'plugins.shell.section.skills',
  subagents: 'plugins.shell.section.subagents',
  brokerages: 'plugins.shell.section.brokerages',
  secrets: 'plugins.shell.section.secrets',
};

// What each section holds, in a line under its title: a first visit cannot
// tell a plugin from a connector from a skill by their names alone.
export const SECTION_DEFINITION_KEYS: Record<Section, string> = {
  apps: 'apps.shell.definition.apps',
  pages: 'plugins.shell.definition.pages',
  plugins: 'plugins.shell.definition.plugins',
  mcp: 'plugins.shell.definition.mcp',
  skills: 'plugins.shell.definition.skills',
  subagents: 'plugins.shell.definition.subagents',
  brokerages: 'plugins.shell.definition.brokerages',
  secrets: 'plugins.shell.definition.secrets',
};

export const SECTION_ICONS: Record<Section, ComponentType<{ className?: string }>> = {
  apps: AppWindow,
  pages: LayoutTemplate,
  plugins: Package,
  mcp: Plug,
  skills: SquareSlash,
  subagents: SubagentsRings,
  brokerages: Landmark,
  secrets: KeyRound,
};

/** The sections that list what can be installed, each with a catalog side. */
export type InstallSection = 'plugins' | 'mcp' | 'skills';
const INSTALLS: readonly Section[] = ['plugins', 'mcp', 'skills'];

/** The sections with a header search and an Add menu: everything the agent
 *  uses, whether or not the catalog carries it yet. */
export type AddSection = InstallSection | 'subagents';

/**
 * The ways in besides the catalog, per section. Each section adds only its
 * own kind: a skill upload offered on Connectors lands on a section the user
 * did not ask for. `hintKey` is the item's second line.
 */
export interface AddRoute {
  intent: AddIntent;
  key: string;
  hintKey?: string;
  icon?: ComponentType<{ className?: string }>;
}

export const ADD_ROUTES: Record<AddSection, AddRoute[]> = {
  plugins: [{ intent: 'plugin', key: 'plugins.addMenu.installPlugin' }],
  mcp: [
    { intent: 'server', key: 'plugins.addMenu.addServer' },
    { intent: 'import', key: 'plugins.addMenu.importServers' },
    {
      intent: 'hithink',
      key: 'plugins.addMenu.hithinkFinance',
      hintKey: 'plugins.addMenu.hithinkFinanceHint',
    },
  ],
  skills: [{ intent: 'skill', key: 'plugins.addMenu.uploadSkill' }],
  subagents: [
    {
      intent: 'subagent',
      key: 'plugins.addMenu.newSubagent',
      hintKey: 'plugins.addMenu.newSubagentHint',
      icon: FilePlus,
    },
    {
      intent: 'subagent-chat',
      icon: MessageSquarePlus,
      key: 'plugins.addMenu.createWithAgent',
      hintKey: 'plugins.addMenu.createWithAgentHint',
    },
  ],
};

/** Sections whose rows carry a per-workspace scope. */
export const SCOPED: ReadonlySet<Section> = new Set<Section>(['brokerages', 'mcp', 'skills']);

/** A section with a Yours and a Discover view, the catalog on the other side. */
export function hasDiscover(section: Section): section is InstallSection {
  return INSTALLS.includes(section);
}

/** A section with a header search and an Add menu: every Customize one. */
export function hasAdd(section: Section): section is AddSection {
  return section in ADD_ROUTES;
}

/** Every `?tab=` value either page can name, in one place: the two shells
 *  between them host all of these, and a tab outside the set is nobody's. */
const KNOWN: readonly Section[] = [
  'apps',
  'pages',
  'plugins',
  'mcp',
  'skills',
  'subagents',
  'brokerages',
  'secrets',
];

function asSection(param: string | null | undefined): Section | null {
  // A legacy spelling (`?tab=servers`, the old Discover tab) means a section
  // like any other; `normalizeSection` is the one place that knows the pair,
  // so this reader and the redirect cannot disagree about what a tab means.
  const section = normalizeSection(param);
  return section && KNOWN.includes(section as Section) ? (section as Section) : null;
}

/**
 * The section the URL names, among the ones `shell` says this page hosts.
 *
 * A `?detail=` with no tab is still unambiguous about where it is listed, and
 * only that section mounts to resolve it. A tab the page does not host — the
 * connectors one on `/plugins`, most of all — is not this page's to render, so
 * it falls back like an unknown one: a section the page cannot draw would leave
 * a blank column where a stray link is the only thing that got there.
 *
 * The page's default section is named on its shell rather than taken as the
 * first one it lists: `/plugins` shows the page plugins first but opens on
 * Plugins, which is what its own nav item (a bare `/plugins`) lands on.
 */
export function readSection(params: URLSearchParams, shell: PageShell): Section {
  const hosted = (section: Section | null): Section | null =>
    section && shell.sections.includes(section) ? section : null;
  const detail = parseDetail(params);
  return (
    hosted(asSection(params.get('tab'))) ??
    hosted(asSection(detail && DETAIL_KIND_TAB[detail.kind])) ??
    shell.defaultSection
  );
}

/** Yours or Discover, only where the section has both. */
export function readSectionView(params: URLSearchParams, section: Section): SectionView {
  return hasDiscover(section) ? readView(params) : 'yours';
}
