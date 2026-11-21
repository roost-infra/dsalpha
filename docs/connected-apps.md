# Connected apps

Connected apps give a bot tools for external services — GitHub, Gmail, Slack,
Notion and the rest — through a user's own OAuth grants. The shape follows
OpenMausBot's connector model: a marketplace, browser OAuth, multiple accounts
per service, tokens held by the connector provider, and a tool endpoint the
agent calls.

## How it works

1. The user pastes a **Composio project key** (`ak_...`) on `/apps`, or the
   deployment sets `COMPOSIO_API_KEY` and the page uses that.
2. The key is stored in the user's **vault** as `COMPOSIO_API_KEY`; it is
   never returned by an API, written to a prompt, or logged.
3. The backend creates one **Tool Router session** per account
   (`POST /api/v3.1/tool_router/session`) with multi-account enabled, and
   stores the Composio user id, session id and its hosted MCP URL in
   `connected_app_installations`.
4. That MCP URL becomes the ordinary user MCP server **`composio`**, whose
   `x-api-key` header is `${vault:COMPOSIO_API_KEY}`. The connector therefore
   rides the existing path: checked, stored per user, enabled per workspace,
   synced into the sandbox, and visible on the Connectors tab.
5. **Connect** calls the session's `/link` endpoint with the toolkit slug and
   opens the returned `redirect_url` in the browser. The provider token stays
   with Composio; the page only refreshes its account list afterwards.
6. **Disconnect** deletes the connected account with
   `revoke_on_delete=true`, so the upstream grant is revoked rather than only
   hidden locally.

## Per-bot grants

A bot's `connector_tools` map names the apps it may use:

```json
{"github": {"tools": "*"}, "gmail": {"tools": ["GMAIL_FETCH_EMAILS"]}}
```

An empty map (the default) grants every app. Once the map names any app, an app
it omits grants that bot nothing — OpenMausBot's rule. The bot editor shows the
connected apps as checkboxes plus an optional exact-tool field; clearing the
last one stores an explicit `__none__` marker so "no app tools" stays distinct
from "unrestricted". The
allow/deny lists still apply on top, and a tool no connected-app prefix claims
is never filtered by this map.

## In-chat connection card

When a thread's bot has a grant for an app that has no connected account yet,
the chat draws a compact card above the composer (GitHub, Gmail, …) linking to
`/apps`. It reads the bot's `connector_tools` and the account's connected-app
inventory; a bot with no grant map or an already-connected app draws nothing.
It is deliberately a composer-side strip, not a fake bot message.

## What is deliberately not here yet

- **Managed broker.** A deployment either supplies one project key or each
  user supplies their own. The Cloudflare broker that keeps a shared key out of
  clients is an OpenMausBot deployment detail, not ported.

## Managed broker

A deployment that sets one `COMPOSIO_API_KEY` does **not** write it into every
user's vault. The session is created server-side, and the connector points at
this server's MCP proxy:

```
url: https://<PUBLIC_API_BASE_URL>/api/v1/connected-apps/mcp
Authorization: Bearer ${vault:COMPOSIO_CONNECTOR_TOKEN}
```

The vault holds only the random per-account connector token; the installation
row stores its SHA-256 hash. The proxy looks the row up by that hash and adds
the shared key upstream, so a sandbox never receives the deployment key.
Managed mode needs `CONNECTED_APPS_PROXY_BASE_URL` (or `PUBLIC_API_BASE_URL`)
to be a public base the sandbox can reach; without one the page shows the
configuration error and per-user keys still work.

Per-user keys stay on the direct Composio MCP URL and their own vault key.

## Connected-app triggers

An automation can be started by a Composio trigger instead of a schedule:

```json
POST /api/v1/automations
{
  "name": "Triage new issues",
  "instruction": "Read the issue and propose a fix.",
  "trigger_type": "connector",
  "trigger_config": {
    "app": "github",
    "event": "GITHUB_ISSUE_CREATED",
    "filters": {"action": "opened"}
  }
}
```

`trigger_config.app` is the toolkit slug, `event` the Composio event name (or
`*` for every event of that app), and `filters` an optional flat equality match
over the payload. Connector automations have no `next_run_at`, so the due-poller
never claims them.

Composio delivers to:

```
POST /api/v1/connected-apps/events
X-Composio-Webhook-Secret: $COMPOSIO_WEBHOOK_SECRET
{
  "user_id": "<Composio user id>",
  "app": "github",
  "event": "GITHUB_ISSUE_CREATED",
  "payload": {"action": "opened", "title": "…"}
}
```

The server maps the Composio user to its installation, matches active
connector automations, creates the ordinary execution row and dispatches it
through `AutomationScheduler`, so thread strategy, delivery and failure
handling match scheduled runs. The event lands in the run's
`additional_context` as `{"type": "connected_app_event", …}`. Unset
`COMPOSIO_WEBHOOK_SECRET` disables the endpoint.

## Security notes

- Provider tokens are never in dsalpha's database, prompts or renderer.
- The project key is a deployment/user secret in the vault; the MCP header only
  contains the `${vault:...}` reference.
- The OAuth link is returned once to the browser that asked for it and is not
  persisted in chat.
- A session MCP URL is accepted only from `*.composio.dev` (or an explicitly
  configured compatible base), so a compromised upstream response cannot point
  the connector at an arbitrary host.
