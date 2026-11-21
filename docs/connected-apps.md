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

## What is deliberately not here yet

- **Per-bot connector grants.** Every bot reaches the `composio` connector's
  tools. Bot `tools_allow`/`tools_deny` still narrows tools, but there is no
  per-app "all / exact list / none" switch yet.
- **Managed broker.** A deployment either supplies one project key or each
  user supplies their own. The Cloudflare broker that keeps a shared key out of
  clients is an OpenMausBot deployment detail, not ported.
- **Triggers/app events.** Composio triggers are not wired to routines.

## Security notes

- Provider tokens are never in dsalpha's database, prompts or renderer.
- The project key is a deployment/user secret in the vault; the MCP header only
  contains the `${vault:...}` reference.
- The OAuth link is returned once to the browser that asked for it and is not
  persisted in chat.
- A session MCP URL is accepted only from `*.composio.dev` (or an explicitly
  configured compatible base), so a compromised upstream response cannot point
  the connector at an arbitrary host.
