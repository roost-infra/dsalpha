// @vitest-environment node
import { describe, expect, it } from 'vitest';

import {
  HITHINK_SERVERS,
  buildHithinkPayload,
} from '../hithinkPreset';

describe('the Hithink connector preset', () => {
  it('carries every documented data domain on the host that documents it', () => {
    expect(HITHINK_SERVERS).toHaveLength(8);
    expect(new Set(HITHINK_SERVERS.map((server) => server.name)).size).toBe(8);
    for (const server of HITHINK_SERVERS) {
      expect(server.url.startsWith('https://fuyao.aicubes.cn/mcp/')).toBe(true);
    }
  });

  it('builds the import body with one trimmed key in every header', () => {
    const payload = buildHithinkPayload('  ths-key  ');

    expect(Object.keys(payload.mcpServers)).toHaveLength(8);
    for (const server of Object.values(payload.mcpServers)) {
      expect(server.type).toBe('http');
      expect(server.headers).toEqual({ 'X-api-key': 'ths-key' });
    }
  });
});
