/** The Hithink (同花顺) finance connector preset.
 *
 * Eight hosted MCP endpoints, one shared `X-api-key`. A user installs them
 * through the ordinary connector import: the literal key in each header is
 * extracted into the user's vault and replaced by a `${vault:...}` reference,
 * and every row lands switched off until the user turns it on.
 *
 * The URLs and the header name are the ones the vendor documents at
 * https://github.com/Hithink-Tech-Org/Financial-API (docs/mcp.md).
 */

export interface HithinkServer {
  name: string;
  url: string;
}

export const HITHINK_SERVERS: readonly HithinkServer[] = [
  { name: 'hithink_a_share', url: 'https://fuyao.aicubes.cn/mcp/a-share' },
  { name: 'hithink_a_share_index', url: 'https://fuyao.aicubes.cn/mcp/a-share-index' },
  { name: 'hithink_hk_share', url: 'https://fuyao.aicubes.cn/mcp/hk-share' },
  { name: 'hithink_meta', url: 'https://fuyao.aicubes.cn/mcp/meta' },
  { name: 'hithink_fund', url: 'https://fuyao.aicubes.cn/mcp/fund' },
  { name: 'hithink_futures', url: 'https://fuyao.aicubes.cn/mcp/futures' },
  { name: 'hithink_options', url: 'https://fuyao.aicubes.cn/mcp/options' },
  { name: 'hithink_news', url: 'https://fuyao.aicubes.cn/mcp/news' },
];

export const HITHINK_API_KEY_URL = 'https://fuyao.aicubes.cn/admin/';

/** The `{"mcpServers": ...}` body the connector import takes, with the key as
 *  a literal so the import vaults it. */
export function buildHithinkPayload(apiKey: string): {
  mcpServers: Record<string, { type: 'http'; url: string; headers: { 'X-api-key': string } }>;
} {
  const key = apiKey.trim();
  return {
    mcpServers: Object.fromEntries(
      HITHINK_SERVERS.map((server) => [
        server.name,
        {
          type: 'http' as const,
          url: server.url,
          headers: { 'X-api-key': key },
        },
      ]),
    ),
  };
}
