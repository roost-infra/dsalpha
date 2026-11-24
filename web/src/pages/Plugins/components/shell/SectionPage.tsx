import { lazy, Suspense, useRef } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useScrollMemory } from '@/lib/scrollMemory';
import { ListSkeleton } from '@/components/mcp/McpPrimitives';
import { AppsList } from '@/pages/Apps/AppsList';
import { Brokerages } from '../Brokerages';
import { DetailPageProvider } from '../DetailPage';
import { McpServers } from '../McpServers';
import { SkillsList } from '../SkillsList';
import { SubagentsList } from '../subagents/SubagentsList';
import { PluginSecrets } from '../PluginSecrets';
import { PluginsList } from '../PluginsList';
import { BuiltinPagePlugins } from '../BuiltinPagePlugins';
import { WorkspacesLoadNote } from '../WorkspacesLoadNote';
import { DiscoverSummary } from '../discover/DiscoverSummary';
import { PageHeader } from './PageHeader';
import { SectionRail } from './SectionRail';
import { YoursSummary } from './YoursSummary';
import {
  hasDiscover,
  readSection,
  readSectionView,
  SCOPED,
  SECTION_LABEL_KEYS,
  type InstallSection,
  type PageShell,
  type Section,
} from './sections';
import { useShellData } from './useShellData';
import { useCatalogOn } from '../../hooks/useCatalogOn';
import { addIntentHref, type AddIntent } from '../../utils/addParam';
import {
  NEW_SUBAGENT_PARAM,
  parseDetail,
  VIEW_PARAM,
  withDetail,
  type SectionView,
} from '../../utils/detailParam';
import { SCOPE_TAB, type DiscoverScope } from '../../utils/marketplace';
import '../../Plugins.css';

// Its own chunk: the catalog is browsed far less often than the page opens.
const Discover = lazy(() =>
  import('../Discover').then((m) => ({ default: m.Discover })),
);

const DISCOVER_SCOPE = Object.fromEntries(
  Object.entries(SCOPE_TAB).map(([scope, tab]) => [tab, scope]),
) as Record<InstallSection, DiscoverScope>;

/** Where a link into Discover lands on a server with no catalog: the same
 *  section's own list, keeping the search and any detail but a catalog
 *  entry's, which only Discover has. */
function withoutDiscover(params: URLSearchParams, section: Section): URLSearchParams {
  const next =
    parseDetail(params)?.kind === 'catalog' ? withDetail(params, null) : new URLSearchParams(params);
  next.set('tab', section);
  next.delete(VIEW_PARAM);
  return next;
}

function SectionBody({ section, view }: { section: Section; view: SectionView }) {
  if (view === 'discover' && hasDiscover(section)) {
    return (
      <Suspense fallback={<ListSkeleton />}>
        <Discover scope={DISCOVER_SCOPE[section]} />
      </Suspense>
    );
  }
  switch (section) {
    case 'apps':
      return <AppsList />;
    case 'pages':
      return <BuiltinPagePlugins />;
    case 'plugins':
      return <PluginsList />;
    case 'mcp':
      return <McpServers />;
    case 'skills':
      return <SkillsList />;
    case 'subagents':
      return <SubagentsList />;
    case 'brokerages':
      return <Brokerages />;
    case 'secrets':
      return <PluginSecrets />;
  }
}

/**
 * A container page: a rail of the sections it hosts beside one scrolling
 * content column. The URL is the whole state — `?tab=` the section,
 * `?view=discover` the catalog side of a Customize section, `?q=` the header
 * search, `?detail=` an item's page — derived rather than mirrored, so
 * back/forward needs no sync effect and cannot briefly disagree with the
 * address bar.
 *
 * `/apps` ("Connect") and `/plugins` ("Extensions") are the two of them, and
 * they differ only in what `shell` says they host: the same rail, header,
 * footer and section bodies serve both. Keeping one component rather than two
 * is what stops the pair from drifting — a fix to the search field or the
 * detail page belongs to both pages, and a copy would take it to one.
 *
 * This is also where a sign-in that failed or was cancelled puts the user back
 * (the entry's page, the install wizard, the connector form), as the app
 * shell's `ConnectLandingHost` decides on reading the OAuth callback's landing.
 */
export function SectionPage({ shell }: { shell: PageShell }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const data = useShellData();
  const catalogOn = useCatalogOn();

  const section = readSection(searchParams, shell);
  // A link into Discover on a server with no catalog is the one rewrite: the
  // page reads it as the section's own list at once, and the address follows.
  const strayDiscover =
    catalogOn === false && readSectionView(searchParams, section) === 'discover';
  const shown = strayDiscover ? withoutDiscover(searchParams, section) : searchParams;
  const detailRef = parseDetail(shown);
  // The new-subagent form is a page of its own, like a detail.
  const pageOpen = !!detailRef || (section === 'subagents' && shown.has(NEW_SUBAGENT_PARAM));
  const view = readSectionView(shown, section);
  const query = searchParams.get('q') ?? '';
  const sectionLabel = t(SECTION_LABEL_KEYS[section]);

  // Each page, section and view keeps its own place, so a short page is not
  // opened halfway down because the long one before it was — and the same
  // section keeps a separate place on each page that hosts it.
  const pageRef = useRef<HTMLDivElement>(null);
  useScrollMemory(pageRef, `${shell.scrollKey}:${section}:${view}`);

  // The one Add entry point for a page: the intent names its own page and tab
  // (`addIntentHref`), so an Add that opens a connector's drawer sends the user
  // to `/apps` rather than writing a tab this page cannot render. Replace, so
  // the list that acts on the intent can strip it without leaving the Add click
  // behind as a history entry.
  const requestAdd = (intent: AddIntent) => {
    navigate(addIntentHref(intent), { replace: true });
  };

  const setView = (next: SectionView) => {
    const params = withDetail(searchParams, null);
    // The legacy Discover tab names the view itself; it becomes Plugins.
    if (params.get('tab') === 'discover') params.set('tab', 'plugins');
    if (!params.get('tab')) params.set('tab', section);
    if (next === 'discover') params.set(VIEW_PARAM, 'discover');
    else params.delete(VIEW_PARAM);
    setSearchParams(params, { replace: true });
  };

  const setQuery = (next: string) => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next) params.set('q', next);
        else params.delete('q');
        return params;
      },
      { replace: true },
    );
  };

  return (
    <div className="plugins-page">
      {strayDiscover && <Navigate replace to={`?${shown.toString()}`} />}
      {/* Doubles as the window titlebar in the desktop shell; inert
          elsewhere. Above the rail and the scroll port rather than inside
          them, so it stays put once the page is scrolled. */}
      <div className="chrome-drag-strip" aria-hidden="true" />
      <div className="plugins-body">
        <SectionRail shell={shell} section={section} detail={detailRef} data={data} />
        <div ref={pageRef} className="plugins-scroll">
          <div className="plugins-column">
            {!pageOpen && (
              <PageHeader
                section={section}
                view={view}
                summary={
                  view === 'discover' && hasDiscover(section) ? (
                    <div className="plugins-summary">
                      <DiscoverSummary scope={DISCOVER_SCOPE[section]} />
                    </div>
                  ) : (
                    <YoursSummary section={section} data={data} />
                  )
                }
                query={query}
                hasCatalog={catalogOn === true}
                onViewChange={setView}
                onQueryChange={setQuery}
                onAdd={requestAdd}
              />
            )}
            <DetailPageProvider value={{ section: sectionLabel }}>
              {/* Keyed so a section switch swaps at once with a short fade
                  rather than sliding: the rail already says where you went. */}
              <div key={`${section}:${view}`} className="plugins-content">
                {SCOPED.has(section) && <WorkspacesLoadNote />}
                <SectionBody section={section} view={view} />
              </div>
            </DetailPageProvider>
          </div>
        </div>
      </div>
    </div>
  );
}
