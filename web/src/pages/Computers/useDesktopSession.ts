import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { apiErrorObject, apiErrorStatus, formatApiErrorDetail } from '@/api/errors';
import { waitForOnline } from '@/lib/network';
import { invalidateMachine } from '@/pages/ChatAgent/hooks/useComputers';

import { desktopProtocols, desktopSocketAddress, releaseDesktop, requestDesktop, type DesktopRole } from './desktopApi';

type SessionState =
  | { status: 'idle' }
  | { status: 'connecting' | 'connected' | 'reconnecting'; role: DesktopRole }
  | { status: 'closed' | 'revoked' }
  | { status: 'busy'; role: DesktopRole }
  | { status: 'error'; message?: string };

interface Attempt {
  release?: () => Promise<void>;
  disconnect?: () => void;
  stopWatching?: () => void;
}

const RETRIES = 3;
const STABLE_AFTER_MS = 30_000;

function releaseQuietly(release: Attempt['release']): Promise<void> | undefined {
  return release?.().catch(() => {});
}

export function useDesktopSession(computerId: string) {
  const [state, setState] = useState<SessionState>({ status: 'idle' });
  const vnc = useRef<HTMLDivElement>(null);
  const picture = useRef<HTMLImageElement>(null);
  const active = useRef<Attempt | null>(null);
  const queryClient = useQueryClient();

  function dispose() {
    const attempt = active.current;
    active.current = null;
    attempt?.stopWatching?.();
    attempt?.disconnect?.();
    void releaseQuietly(attempt?.release);
  }

  useEffect(() => dispose, []);

  async function start(role: DesktopRole, takeover: boolean, retriesLeft?: number) {
    if (active.current) return;
    const attempt: Attempt = {};
    active.current = attempt;
    setState({ status: retriesLeft === undefined ? 'connecting' : 'reconnecting', role });
    let connectedAt: number | undefined;

    function finish(next: SessionState) {
      if (active.current !== attempt) return;
      dispose();
      setState(next);
    }

    function connected() {
      if (active.current !== attempt || connectedAt !== undefined) return;
      connectedAt = performance.now();
      const offline = () => { void recover(); };
      window.addEventListener('offline', offline);
      attempt.stopWatching = () => window.removeEventListener('offline', offline);
      setState({ status: 'connected', role });
    }

    async function recover() {
      if (active.current !== attempt) return;
      const remaining = connectedAt !== undefined && performance.now() - connectedAt >= STABLE_AFTER_MS
        ? RETRIES : (retriesLeft ?? RETRIES);
      if (remaining === 0) {
        finish({ status: 'error' });
        return;
      }
      const release = attempt.release;
      const pending: Attempt = { release };
      active.current = pending;
      attempt.stopWatching?.();
      attempt.disconnect?.();
      setState({ status: 'reconnecting', role });
      await new Promise<void>((resolve) => {
        const timer = window.setTimeout(resolve, 500 * 2 ** (RETRIES - remaining));
        pending.disconnect = () => { window.clearTimeout(timer); resolve(); };
      });
      if (active.current !== pending) return;
      if (!await waitForOnline(30_000)) {
        if (active.current === pending) {
          active.current = null;
          setState({ status: 'error' });
        }
        return;
      }
      if (active.current !== pending) return;
      await releaseQuietly(release);
      if (active.current !== pending) return;
      active.current = null;
      // A reconnect may reacquire an empty lease, but never displaces another browser.
      void start(role, false, remaining - 1);
    }

    function closed(event: CloseEvent) {
      if (event.code === 1008) finish({ status: 'revoked' });
      else if (event.code === 1000) finish({ status: 'closed' });
      else if (connectedAt !== undefined || retriesLeft !== undefined) void recover();
      else finish({ status: 'error' });
    }

    try {
      const session = await requestDesktop(computerId, role, takeover);
      attempt.release = () => releaseDesktop(computerId, session.session_id);
      // A late grant still needs releasing if the user navigates away while it is minted.
      if (active.current !== attempt) {
        void releaseQuietly(attempt.release);
        return;
      }
      if (retriesLeft === undefined) invalidateMachine(queryClient);
      const url = desktopSocketAddress(session.ws_url);
      const protocols = desktopProtocols(session.ticket);
      if (session.transport === 'screenshot' && role === 'view' && picture.current) {
        const img = picture.current;
        const socket = new WebSocket(url, protocols);
        socket.binaryType = 'arraybuffer';
        let frameUrl: string | null = null;
        socket.addEventListener('message', (event: MessageEvent<ArrayBuffer>) => {
          if (active.current !== attempt || !(event.data instanceof ArrayBuffer)) return;
          if (frameUrl) URL.revokeObjectURL(frameUrl);
          frameUrl = URL.createObjectURL(new Blob([event.data], { type: 'image/jpeg' }));
          img.src = frameUrl;
          connected();
        });
        socket.addEventListener('close', closed);
        attempt.disconnect = () => {
          socket.close();
          img.removeAttribute('src');
          if (frameUrl) URL.revokeObjectURL(frameUrl);
        };
      } else if ((session.transport === 'novnc' || session.transport === 'vnc-ws') && vnc.current) {
        // noVNC 1.6+ uses top-level await, which splits the Vite HTML entry
        // that the version manifest and the platform deployment both read.
        const { default: entry } = await import('@novnc/novnc');
        const RFB = typeof entry === 'function' ? entry : entry.default;
        if (active.current !== attempt) return;
        const socket = new WebSocket(url, protocols);
        attempt.disconnect = () => socket.close();
        socket.addEventListener('close', closed);
        const client = new RFB(vnc.current, socket);
        client.scaleViewport = true;
        client.addEventListener('connect', connected);
        client.addEventListener('credentialsrequired', () => finish({ status: 'error' }));
        client.addEventListener('securityfailure', () => finish({ status: 'error' }));
        attempt.disconnect = () => {
          client.disconnect();
          socket.close();
        };
      } else {
        finish({ status: 'error' });
      }
    } catch (error) {
      const status = apiErrorStatus(error);
      if (apiErrorObject(error)?.code === 'desktop_busy') {
        finish({ status: 'busy', role });
      } else if (retriesLeft !== undefined && (status === null || status >= 500)) {
        void recover();
      } else {
        finish({ status: 'error', message: formatApiErrorDetail(error) });
      }
    }
  }

  function connect(role: DesktopRole, takeover = false) {
    return start(role, takeover);
  }

  function disconnect() {
    dispose();
    setState({ status: 'idle' });
  }

  return { state, vnc, picture, connect, disconnect };
}
