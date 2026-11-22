# Upstream chat migration matrix

Upstream: `ginlix-ai/LangAlpha` main at `ec50d7b3e` (2026-11-22).
Fork base: `4717097d1` (2026-11-06). We are 250 commits ahead; upstream is 740
ahead (3,226 files, +293,065/−40,132). A whole merge produced 71 conflicting
files before migration work.

This branch ports chat/UX work **commit by commit**, not by merging upstream
wholesale. Each batch is testable on its own; commits that depend on a whole
upstream subsystem are deferred rather than half-applied.

## Ported

| Upstream | What | Local commit | Notes |
|---|---|---|---|
| `5ea9e06e3` | Count-of-steps opens/closes as one fold | `bc977e2ed` | clean |
| `eacdbc143` | Jump offered when an opened row leaves the end out of view | `6c6fb8c4f` | clean |
| `0aa5fa7f4` | e2e pins for the fold and jump | `30b27eed9` | clean |
| `212571f35` | Markdown link reading linear time | `7f5f046f7` | ported onto our older `tools/secretary/utils.py` route |
| `b81a60d0e` | Each Task's checkpoints in its own namespace | `2a5b222cb` | clean |
| `af1b00923` | Concurrent thread numbering under a lock | `fcb8101a5` | clean; touches our thread create/home-fold path |
| `07226dd1c` | Postgres regression for the thread-index race | `d3bc0282f` | integration test |
| `d558fdd51` | SSE delta goes out at once after a quiet spell | `4d98505fb` | core coalescer only; relay half depends on `6b99a6c32` |
| `903c38a84` | thread load ends at its replay, not its ratings read | `1f37e9cf5` | adapted; adds `feedbackLoading` to our older hook |
| `0a52c7dec` | keep an earlier report's start when the newest turn wrote nothing | `5bfc4441b` | ported onto `tools/secretary/utils.py` |
| `b5437c5e0` | show/refresh watched orders and order wakeups | `8ac5e9ed1` | clean; order wakeup backend remains upstream-only |
| `ed4c67f51` | home clocks for TWII/KS11/NSEI/BSESN/AXJO indices | `0112791b9` | adapted; our table predates `SessionHours`, so timezone only |

## Deferred: dependency or semantic conflict

| Upstream | Why not yet |
|---|---|
| `f5d61083a` / `c9127b134` (turn fold by answer) | Dependency chain: `9c10553bb` adds `chartLayerGrouping` / `cardedCharts`; `d78b9e503` adds quiet-turn ends (`replyEnds`, `quietEnd`); `650819ba2` / `06ef07733` add the context hand-off and notice types (`textsFollowed`). All of those touch our `MessageList` / `ChatView` / `buildRenderBlocks`; 4-file conflict and a semantic rewrite. Port the projection layer as one unit. |
| `19829836f` (source cost + provider icon) | UI is small, but backend provenance does not yet emit `cost_credits` / `site`; porting only the panel would render nothing. |
| `cb8cc1dcc` (fold composer tray under notices) | Needs `useNoticeSlot`, `useTrayFold.covered`, `othersTurn`; those are not in this fork. |
| `d558fdd51` relay half | `DeltaJoin` arrives in upstream `6b99a6c32`; our relay predates it. |
| `9e365f931`, `1a20c1c1e` | Depend on upstream `turn_tool.py` and background-subagent refactors not present here. |
| `ab972510b`, `fbcbcbdfb`, `4cde70a7f` (forks) | Cross-cut `threads`, `context_stack`, runtime-context, ChatView, and session state; needs a dedicated feature branch. |
| `7a9da0937`, `42ea097ce` (comments) | Comments backend, preview bridge, models and anchors are a separate subsystem; 22 conflicts for the first commit. |
| `a25a926f6` (browser tab) | Needs `browser_runtime`, `workspace_browser`, preview capabilities and a newer FilePanel; 14 conflicts. |
| `06ef07733` (Claude Code wait UI) | Needs upstream computer/CLI state and Job view; 15 conflicts. |

## Clean but not taken yet

- `b5437c5e0` watched-order summary — depends on upstream order/wakeup model.
- `4c6b5bc6a` browser-stream test — no browser runtime here yet.
- `4198e82ff` turn-fold tests — test the deferred `f5d61083a`; take with that batch.
- `457a5dae5` build ceiling bump — only after measuring our bundle.

## Conflict hotspots from a full merge

`README*`, `agent_config.yaml`, `src/config/env.py`, `features.py`,
`ptc_agent/agent/agent.py`, `server/app/setup.py`, `threads/*`,
`home_fold.py`, `automation_executor.py`, `web/src/pages/Dashboard/*`,
`navItems.ts`, `ChatView.tsx`, `locales/*`.

## Next batches

1. **Projection layer**: upstream history/fold helpers (`replyEnds`,
   `quietEnd`, `cardedCharts`) then `f5d` + `c912` + `4198`.
2. **Provenance**: backend `cost_credits`/`site` then `19829836f`.
3. **Load/reconnect**: `useChatFeedback`/`useChatMessages` load order then
   `903c38a84`.
4. **Forks**: `threads` + `context_stack` + session resume, as one feature.
5. **Comments**, **browser**, **Claude Code** remain separate subsystem ports.
