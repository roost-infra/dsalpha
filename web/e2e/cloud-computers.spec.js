import { Buffer } from 'node:buffer';

import { mockAPI, test, expect } from './fixtures.js';
import { sampleWorkspace } from './helpers/mockResponses.js';

const COMPUTER_ID = 'c0000001-0000-4000-8000-000000000001';
const WORKSPACE_ID = 'a0000001-0000-4000-8000-000000000001';
const SESSION_ID = 'e0000001-0000-4000-8000-000000000001';
const WS_PATH = `/ws/v1/computers/${COMPUTER_ID}/desktop`;
const DESKTOP_ROUTE = `/computers/${COMPUTER_ID}/desktop`;
const COMPUTER = {
  computer_id: COMPUTER_ID, user_id: 'local-dev-user', name: 'Research Linux', kind: 'daytona',
  provider_ref: 'sandbox-1', status: 'running', os_platform: 'linux', desktop_transport: 'novnc',
  desktop_state: 'off', resource_tier: 'standard', region: 'us-west', estimated_credits: 32,
};

test('opens a desktop, releases its session, and links back through workspace files', async ({ page }) => {
  const workspace = sampleWorkspace({ workspace_id: WORKSPACE_ID, computer_id: COMPUTER_ID });
  let connected = false;
  let released = false;
  await page.routeWebSocket(`**${WS_PATH}`, () => { connected = true; });
  await mockAPI(page, {
    'GET /computers': { computers: [COMPUTER] },
    'GET /computers/providers': { providers: [{ kind: 'daytona', is_default: true, os_platforms: ['linux'], supports_ssh: true }] },
    'GET /workspaces': { workspaces: [workspace], total: 1 },
    'GET /workspaces/*': workspace,
    'GET /workspaces/*/files': { files: [] },
    [`POST /computers/${COMPUTER_ID}/desktop/session`]: async (route) => {
      expect(route.request().postDataJSON()).toEqual({ role: 'view' });
      await route.fulfill({ json: { role: 'view', transport: 'screenshot', ticket: 'test-ticket', session_id: SESSION_ID, ws_url: WS_PATH } });
    },
    [`DELETE /computers/${COMPUTER_ID}/desktop/session/${SESSION_ID}`]: async (route) => {
      released = true;
      await route.fulfill({ status: 204 });
    },
  });

  await page.goto('/computers');
  const card = page.getByRole('article', { name: 'Research Linux' });
  await expect(card).toContainText('32 credits');
  await card.getByRole('link', { name: 'Open desktop' }).click();
  await expect(page).toHaveURL(new RegExp(`${DESKTOP_ROUTE}$`));
  await page.getByRole('button', { name: 'View only' }).click();
  await expect.poll(() => connected).toBe(true);

  await page.getByRole('link', { name: 'Browse files' }).click();
  await expect.poll(() => released).toBe(true);
  await expect(page).toHaveURL(new RegExp(`/chat/${WORKSPACE_ID}\\?panel=files$`));
  await page.getByRole('button', { name: 'Open desktop' }).click();
  await expect(page).toHaveURL(new RegExp(`${DESKTOP_ROUTE}\\?workspace=${WORKSPACE_ID}$`));
});

test('negotiates an RFB desktop and displays the controller canvas', async ({ page }) => {
  const version = Buffer.from('RFB 003.008\n');
  const name = Buffer.from('Test desktop');
  // RFB ServerInit: 2x2 framebuffer, 32 bpp with 24-bit RGB, then its name.
  const init = Buffer.from([0, 2, 0, 2, 32, 24, 0, 1, 0, 255, 0, 255, 0, 255, 16, 8, 0, 0, 0, 0, 0, 0, 0, name.length]);
  await page.routeWebSocket(`**${WS_PATH}`, (socket) => {
    let step = 0;
    socket.onMessage((message) => {
      switch (step++) {
        case 0:
          expect(message).toEqual(version);
          socket.send(Buffer.from([1, 1])); // One security type, None.
          break;
        case 1:
          expect(message).toEqual(Buffer.from([1]));
          socket.send(Buffer.alloc(4)); // SecurityResult succeeded.
          break;
        case 2:
          socket.send(Buffer.concat([init, name]));
          break;
      }
    });
    socket.send(version);
  });

  await mockAPI(page, {
    'GET /computers': { computers: [COMPUTER] },
    [`POST /computers/${COMPUTER_ID}/desktop/session`]: async (route) => {
      expect(route.request().postDataJSON()).toEqual({ role: 'control' });
      await route.fulfill({ json: { role: 'control', transport: 'novnc', ticket: 'test-ticket', session_id: SESSION_ID, ws_url: WS_PATH } });
    },
    [`DELETE /computers/${COMPUTER_ID}/desktop/session/${SESSION_ID}`]: (route) => route.fulfill({ status: 204 }),
  });

  await page.goto(DESKTOP_ROUTE);
  await page.evaluate(() => {
    // Playwright's routed WebSocket adds a subclass. noVNC checks the direct
    // prototype, where browsers expose these methods on a native socket.
    const prototype = WebSocket.prototype;
    const parent = Object.getPrototypeOf(prototype);
    for (const key of ['send', 'close', 'binaryType', 'onerror', 'onmessage', 'onopen', 'protocol', 'readyState']) {
      const descriptor = Object.getOwnPropertyDescriptor(parent, key);
      if (descriptor && !Object.hasOwn(prototype, key)) Object.defineProperty(prototype, key, descriptor);
    }
  });
  await page.getByRole('button', { name: 'Take control' }).click();
  await expect(page.locator('canvas')).toBeVisible();
  await page.getByRole('button', { name: 'Disconnect' }).click();
  await expect(page.locator('canvas')).toHaveCount(0);
});
