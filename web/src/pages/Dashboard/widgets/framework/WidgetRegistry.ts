import type { WidgetDefinition } from '../types';

const registry = new Map<string, WidgetDefinition<unknown>>();

/** Widget type → the built-in plugin that owns it, for types registered by
 *  plugin contribution modules rather than the core dashboard. */
const owners = new Map<string, string>();

export function registerWidget<C>(def: WidgetDefinition<C>): void {
  registry.set(def.type, def as WidgetDefinition<unknown>);
}

/** Mark a set of already-registered widgets as a plugin contribution. */
export function setWidgetPlugin(types: readonly string[], pluginId: string): void {
  for (const type of types) owners.set(type, pluginId);
}

export function getWidget(type: string): WidgetDefinition<unknown> | undefined {
  return registry.get(type);
}

export function widgetPlugin(type: string): string | undefined {
  return owners.get(type);
}

/** All widgets, or only those whose owning plugin is enabled. Core widgets
 *  (no owner) always pass. */
export function listWidgets(enabledPlugins?: ReadonlySet<string>): WidgetDefinition<unknown>[] {
  const all = Array.from(registry.values());
  if (!enabledPlugins) return all;
  return all.filter((def) => {
    const owner = owners.get(def.type);
    return !owner || enabledPlugins.has(owner);
  });
}

export function listWidgetsByCategory(
  enabledPlugins?: ReadonlySet<string>,
): Record<string, WidgetDefinition<unknown>[]> {
  const grouped: Record<string, WidgetDefinition<unknown>[]> = {};
  for (const def of listWidgets(enabledPlugins)) {
    if (!grouped[def.category]) grouped[def.category] = [];
    grouped[def.category].push(def);
  }
  return grouped;
}
