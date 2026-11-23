# Entry bundle report — 2026-11-23

Built from `perf/page-load-cloudflare` (base `d4e8f5722`) with the production
Vite config, plus a temporary Rolldown `generateBundle` reporter that emits
per-module `renderedLength`. The table below is the `assets/index-*.js` entry
chunk, not a browser request trace.

> These are module bytes inside the entry chunk before the final minifier. They
> rank what the entry pulls in; the shipped entry is ~690KB raw / ~232KB br.

## Top packages in the entry

| # | Package / area | Module bytes | Why it is eager |
|---:|---|---:|---|
| 1 | `@supabase/auth-js` | 171.1 KB | Auth bootstrap and token cache import the client at module load |
| 2 | `i18next` + react-i18next | 73.5 KB | App-wide translations, loaded before the shell renders |
| 3 | `@tanstack/query-core` | 70.2 KB | Query client is created with the app shell |
| 4 | `zod` | 60.9 KB | Schemas imported by shell/forms rather than form chunks |
| 5 | `tailwind-merge` | 55.4 KB | `cn()` utility imported by the shell |
| 6 | `NavigationRows.tsx` | 44.3 KB | Chat navigation tree is imported by the always-on sidebar |
| 7 | `lucide-react` | 38.8 KB | Icons used by the shell/navigation |
| 8 | `@radix-ui/react-menu` | 30.8 KB | Account and row menus |
| 9 | `@radix-ui/react-toast` | 23.3 KB | App toast provider |
| 10 | `App.tsx` | 20.0 KB | Routes/shell composition |

## Largest individual modules

| Module | Module bytes |
|---|---:|
| `@supabase/auth-js/dist/module/GoTrueClient.js` | 106.1 KB |
| `i18next/dist/esm/i18next.js` | 73.5 KB |
| `tailwind-merge/dist/bundle-mjs.mjs` | 55.4 KB |
| `src/pages/ChatAgent/components/NavigationRows.tsx` | 44.3 KB |
| `@radix-ui/react-menu/dist/index.mjs` | 30.8 KB |
| `zod/v4/core/schemas.js` | 28.2 KB |
| `@radix-ui/react-toast/dist/index.mjs` | 23.3 KB |
| `src/App.tsx` | 20.0 KB |
| `@floating-ui/core/dist/floating-ui.core.mjs` | 19.2 KB |
| `src/hooks/useArtifact.ts` | 19.0 KB |

## Actionable cuts

1. **Move Chat navigation behind a lazy boundary.**
   `NavigationRows` (44.3 KB) plus `useNavigationData` (17.8 KB), `navTreeKit`
   (12.5 KB), `WorkspaceConversations` (14.0 KB), and `agentPaths` (13.6 KB)
   are entry bytes because the sidebar imports the chat navigation eagerly.
   Render a small sidebar placeholder while the tree chunk loads. This is the
   lowest-risk app-level cut — roughly 90–100 KB of entry modules.

2. **Lazy-load `ThreadSharePanel` and `useComputers`.**
   They are chat/share surfaces, not needed to paint the shell. ~33 KB of
   module bytes between them.

3. **Move Zod schemas to the form/dialog chunks that use them.**
   The entry imports schemas for widgets/forms that already have lazy panels.
   This is a broader change; do it after the sidebar split.

4. **`tailwind-merge` (55.4 KB)** is only used by `cn()`. Check whether the
   shell can use `clsx` alone and let panels import `twMerge`; do not replace
   globally without checking class-conflict behavior.

5. **Do not lazy-load the auth client, i18n or query-core blindly.** They are
   on the sign-in/shell path; splitting them trades a smaller entry for a
   second round trip before the app can decide whether the user is signed in.
   Optimize their imports (tree-shaking, narrower modules) before splitting.

Target: entry under ~600 KB raw / ~190 KB br. The Cloudflare shell cache and
purge in the same PR remove the HTML TTFB; bundle cuts then reduce the payload
that follows.

## Reproduce

```bash
cd web
npx vite build
# temporary reporter: emit chunk.modules[].renderedLength from generateBundle
```
