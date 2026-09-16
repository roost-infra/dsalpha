/**
 * The product mark, drawn rather than fetched: a rising trend line with its
 * peak marked.
 *
 * Inline and stroked in `currentColor` so it takes the tint of whatever tile it
 * sits in — the same mark reads on a light bed and a dark one without a second
 * asset, and it cannot drift from the theme the way a pair of theme-picked
 * files does. The favicons keep their own opaque beds because a browser tab has
 * no surface to inherit; a tile in a list does.
 */
export function AthenaMark({ className = '' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 60 60"
      fill="none"
      aria-hidden
      className={className}
    >
      <path
        d="M11 43.5L23.5 30.5L33 37L49 17.5"
        stroke="currentColor"
        strokeWidth={4.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="49" cy="17.5" r="5.5" fill="currentColor" />
      <path
        d="M11 52.5H49"
        stroke="currentColor"
        strokeWidth={3.5}
        strokeLinecap="round"
        opacity={0.28}
      />
    </svg>
  );
}
