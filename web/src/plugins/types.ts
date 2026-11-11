/** A page plugin is a first-party package compiled into the app. */
import type { ComponentType, LazyExoticComponent } from 'react';
import type { LucideIcon } from 'lucide-react';

export interface PagePluginPage {
  id: string;
  /** Route inside the plugin host, e.g. `/p/market`. */
  path: string;
  labelKey: string;
  component: LazyExoticComponent<ComponentType>;
}

export interface PagePlugin {
  id: string;
  /** i18n keys, never display text: the app carries both locales. */
  nameKey: string;
  descriptionKey: string;
  icon: LucideIcon;
  defaultEnabled: boolean;
  pages: PagePluginPage[];
}
