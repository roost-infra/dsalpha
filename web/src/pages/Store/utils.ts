import type { MarketCategory } from './api';

/** The display label for a bot's category id, from the list answer's chips. */
export function categoryLabelOf(
  categories: readonly MarketCategory[] | undefined,
  id: string | undefined,
): string | undefined {
  if (!id) return undefined;
  return categories?.find((category) => category.id === id)?.label;
}
