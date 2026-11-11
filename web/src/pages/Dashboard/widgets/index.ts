// Importing each module registers its widget as a side effect.
import './core';
// The market-center plugin's dashboard contribution registers its widgets and
// marks them owned by the plugin; the dashboard filters them when it is off.
import './market';

export { listWidgets, listWidgetsByCategory, getWidget, widgetPlugin } from './framework/WidgetRegistry';
