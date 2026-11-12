import { describe, expect, it } from 'vitest';
import { PAGE_PLUGINS, pagePluginById, pagePluginForRoute } from '../registry';

describe('built-in page plugin routes', () => {
  it('resolves the plugin id and the page id used by /p/:routeId', () => {
    expect(pagePluginById('market-center')?.id).toBe('market-center');
    expect(pagePluginForRoute('market-center')?.id).toBe('market-center');
    // The URL is /p/market; the manifest id is the longer one.
    expect(pagePluginForRoute('market')?.id).toBe('market-center');
    expect(pagePluginForRoute('content-desk')?.id).toBe('content-desk');
  });

  it('returns null for an unknown route without inventing a page', () => {
    expect(pagePluginForRoute('not-a-plugin')).toBeNull();
  });

  it('ships the page plugins off by default', () => {
    expect(PAGE_PLUGINS.find((p) => p.id === 'market-center')?.defaultEnabled).toBe(false);
    expect(PAGE_PLUGINS.find((p) => p.id === 'content-desk')?.defaultEnabled).toBe(false);
  });
});
