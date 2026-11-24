import { Fragment, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { BrandMark } from '@/pages/ChatAgent/components/mcp/BrandMark';
import type { PluginInfo } from '@/pages/ChatAgent/utils/api';
import type { DetailRef } from '../../utils/detailParam';
import { pluginMark } from '../../utils/pluginSurface';
import { StatusDot } from '../surface/Surface';
import {
  SECTION_ICONS,
  SECTION_LABEL_KEYS,
  type PageShell,
  type Section,
} from './sections';
import { connectorAttention, type ShellData } from './useShellData';

/**
 * A container page's own navigation: the sections the page hosts, then — on the
 * page that lists installed plugins — every one of them as a one-click hop to
 * its page, with the bundled ones folded under "Built in".
 *
 * Both pages draw through this, and the page hands it the sections, so the rail
 * cannot offer a section its page does not render. The installed list is
 * omitted where the page does not list plugins at all (`/apps`), since a jump
 * list into a section this page does not show would navigate away from it.
 *
 * The installed list itself is a jump list, not a second inventory: a logo, a
 * name and a dot when something needs the user. Counts and states stay on the
 * cells, so the rail never says the same thing twice beside them. It stays on
 * every section of the page that has it, Plugins → Yours included: a rail that
 * changes shape between tabs reads as navigation that moved, which costs more
 * than one list shown beside the grid it mirrors.
 */
export function SectionRail({
  shell,
  section,
  detail,
  data,
}: {
  shell: PageShell;
  section: Section;
  detail: DetailRef | null;
  data: ShellData;
}) {
  const { t } = useTranslation();
  // The jump list belongs to the page that actually lists plugins. `/apps`
  // hosts none, so its rail is the sections alone.
  const withPlugins = shell.sections.includes('plugins');
  const installed = withPlugins ? (data.plugins?.installed ?? []) : [];
  const builtIn = withPlugins ? (data.plugins?.builtIn ?? []) : [];
  const problems = data.plugins?.problems;

  // A plugin page opened from here lights its own entry, not the section's.
  const openPlugin = detail?.kind === 'plugin' ? detail.name : null;
  const pluginInRail =
    openPlugin !== null && [...installed, ...builtIn].some((p) => p.name === openPlugin);
  const openBuiltIn = openPlugin !== null && builtIn.some((p) => p.name === openPlugin);

  // Collapsed by default, and unfolded once by a bundled plugin's page so its
  // entry is in view; folding it again after that is the user's call.
  const [builtInOpen, setBuiltInOpen] = useState(false);
  const [revealedFor, setRevealedFor] = useState<string | null>(null);
  if (openBuiltIn && openPlugin !== revealedFor) {
    setRevealedFor(openPlugin);
    setBuiltInOpen(true);
  }
  const builtInAttention = builtIn.some((p) => problems?.has(p.name));

  const counts: Partial<Record<Section, number | null>> = {
    pages: null,
    plugins: data.plugins ? installed.length + builtIn.length : null,
    mcp: data.connectors?.total ?? null,
    skills: data.skills?.total ?? null,
    subagents: data.subagents?.total ?? null,
    brokerages: data.brokerages?.connected ?? null,
    secrets: data.secrets,
  };
  const attention: Partial<Record<Section, boolean>> = {
    pages: false,
    // The installed entries carry each plugin's dot right below.
    plugins: false,
    mcp: !!data.connectors && connectorAttention(data.connectors) > 0,
    skills: false,
    subagents: !!data.subagents && data.subagents.attention > 0,
    brokerages: !!data.brokerages && data.brokerages.signIn > 0,
    secrets: false,
  };

  // On a phone the rail is a row of pills wider than the screen; the one the
  // page is on is brought into view rather than left past the edge. On the
  // desktop rail every entry already is, so this moves nothing. Again whenever
  // a count or a dot lands: each widens the pills before the current one and
  // pushes it back past the edge it was just brought inside.
  const pillShape = shell.sections
    .map((s) => `${counts[s] ?? ''}${attention[s] ? '*' : ''}`)
    .join('|');
  const navRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const current = navRef.current?.querySelector<HTMLElement>('[aria-current="page"]');
    current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [section, openPlugin, pillShape]);

  // A section link stays on the page the rail belongs to: the href names the
  // page, because a rail entry on `/apps` must not send the user to absent
  // `/plugins?tab=apps`, and vice versa.
  const sectionLink = (s: Section) => {
    const Icon = SECTION_ICONS[s];
    const active = s === section && !pluginInRail;
    const count = counts[s];
    return (
      <Link
        key={s}
        to={`${shell.path}?tab=${s}`}
        className={cn('plugins-rail-link', active && 'is-active')}
        aria-current={active ? 'page' : undefined}
      >
        <Icon className="plugins-rail-icon" aria-hidden />
        <span className="plugins-rail-name">{t(SECTION_LABEL_KEYS[s])}</span>
        {attention[s] && (
          <>
            <StatusDot tone="attn" />
            <span className="sr-only">{t('plugins.shell.needsAttention')}</span>
          </>
        )}
        {/* A zero says nothing a name does not: no brokerage connected, no
            key stored. */}
        {!!count && <span className="plugins-rail-count">{count}</span>}
      </Link>
    );
  };

  const pluginLink = (plugin: PluginInfo) => {
    const active = plugin.name === openPlugin;
    const problem = problems?.has(plugin.name);
    const search = new URLSearchParams({ tab: 'plugins', detail: `plugin:${plugin.name}` });
    return (
      <Link
        key={plugin.name}
        to={`${shell.path}?${search.toString()}`}
        className={cn('plugins-rail-link', active && 'is-active', !plugin.enabled && 'is-off')}
        aria-current={active ? 'page' : undefined}
        title={plugin.name}
      >
        <BrandMark name={plugin.name} size="xs" className="plugins-rail-mark" {...pluginMark(plugin)} />
        <span className="plugins-rail-name">{plugin.name}</span>
        {!plugin.enabled && <span className="sr-only">{t('plugins.shell.pluginOff')}</span>}
        {problem && (
          <>
            <StatusDot tone="attn" />
            <span className="sr-only">{t('plugins.shell.needsAttention')}</span>
          </>
        )}
      </Link>
    );
  };

  return (
    <nav ref={navRef} className="plugins-rail" aria-label={t(shell.railLabelKey)}>
      {/* Groups are flattened into the rail rather than wrapped: the rail's
          first heading trims its own top margin, and on a phone the rail
          becomes a single row of pills, so an intermediate box would put the
          margins inside it and hide the pills behind it. */}
      {shell.groups.map((group, i) => (
        <Fragment key={group.labelKey ?? `group-${i}`}>
          {group.labelKey && <div className="plugins-rail-label">{t(group.labelKey)}</div>}
          {group.sections.map(sectionLink)}
        </Fragment>
      ))}

      {/* The label heads the built-in fold as well: without it, an account
          with only bundled plugins showed "Built in" straight under Accounts,
          read as one more account section. */}
      {installed.length + builtIn.length > 0 && (
        <div className="plugins-rail-label">{t('plugins.shell.group.installed')}</div>
      )}
      {installed.length > 0 && <div className="plugins-rail-plugins">{installed.map(pluginLink)}</div>}
      {builtIn.length > 0 && (
        <div className="plugins-rail-plugins">
          <button
            type="button"
            className="plugins-rail-link plugins-rail-fold"
            aria-expanded={builtInOpen}
            onClick={() => setBuiltInOpen((open) => !open)}
          >
            <span className="plugins-rail-chevron" aria-hidden>
              <ChevronRight className={cn('h-3.5 w-3.5', builtInOpen && 'rotate-90')} />
            </span>
            <span className="plugins-rail-name">{t('plugins.shell.group.builtIn')}</span>
            {!builtInOpen && builtInAttention && <StatusDot tone="attn" />}
            <span className="plugins-rail-count">{builtIn.length}</span>
          </button>
          {builtInOpen && builtIn.map(pluginLink)}
        </div>
      )}
    </nav>
  );
}
