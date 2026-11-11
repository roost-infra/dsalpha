import { describe, expect, it } from 'vitest';
import '../index';
import { listWidgets, widgetPlugin } from '../framework/WidgetRegistry';
import { PRESETS_META } from '../presets';

describe('market-center dashboard contribution', () => {
  it('owns the financial widgets and leaves core widgets unowned', () => {
    expect(widgetPlugin('markets.overview')).toBe('market-center');
    expect(widgetPlugin('chart.symbol')).toBe('market-center');
    expect(widgetPlugin('tv.ticker-tape')).toBe('market-center');
    expect(widgetPlugin('agent.conversation')).toBeUndefined();
    expect(widgetPlugin('threads.recent')).toBeUndefined();
  });

  it('hides contributed widgets when the plugin is off', () => {
    const off = listWidgets(new Set());
    const on = listWidgets(new Set(['market-center']));
    expect(off.some((widget) => widget.type === 'markets.overview')).toBe(false);
    expect(on.some((widget) => widget.type === 'markets.overview')).toBe(true);
    expect(off.some((widget) => widget.type === 'agent.conversation')).toBe(true);
  });

  it('marks financial presets as plugin-contributed and keeps the assistant preset core', () => {
    expect(PRESETS_META.find((preset) => preset.id === 'assistant')?.pluginId).toBeUndefined();
    expect(PRESETS_META.find((preset) => preset.id === 'morning-brief')?.pluginId).toBe('market-center');
  });
});
