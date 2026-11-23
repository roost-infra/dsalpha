import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { apiErrorObject, formatApiErrorDetail } from '@/api/errors';
import { invalidateMachine } from '@/pages/ChatAgent/hooks/useComputers';

import { desktopProtocols, desktopSocketAddress, releaseDesktop, requestDesktop, type DesktopRole } from './desktopApi';

type SessionState =
  | { status: 'idle' }
  | { status: 'connecting' | 'connected'; role: DesktopRole }
  | { status: 'closed' }
  | { status: 'busy'; role: DesktopRole }
  | { status: 'error'; message?: string };

interface Attempt {
  release?: () => void;
  disconnect?: () => void;
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
    attempt?.disconnect?.();
    attempt?.release?.();
  }

  useEffect(() => dispose, []);

  async function connect(role: DesktopRole, takeover = false) {
    if (active.current) return;
    const attempt: Attempt = {};
    active.current = attempt;
    setState({ status: 'connecting', role });

    function finish(next: SessionState) {
      if (active.current !== attempt) return;
      dispose();
      setState(next);
    }

    try {
      const session = await requestDesktop(computerId, role, takeover);
      attempt.release = () => { void releaseDesktop(computerId, session.session_id).catch(() => {}); };
      // A late grant still needs releasing if the user navigates away while it is minted.
      if (active.current !== attempt) {
        attempt.release();
        return;
      }
      invalidateMachine(queryClient);
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
          setState((current) => current.status === 'connected' ? current : { status: 'connected', role });
        });
        socket.addEventListener('close', (event) => finish({ status: event.wasClean ? 'closed' : 'error' }));
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
        const client = new RFB(vnc.current, url, { wsProtocols: protocols });
        client.scaleViewport = true;
        client.addEventListener('connect', () => {
          if (active.current === attempt) setState({ status: 'connected', role });
        });
        client.addEventListener('disconnect', (event) => {
          const clean = (event as CustomEvent<{ clean: boolean }>).detail?.clean;
          finish({ status: clean ? 'closed' : 'error' });
        });
        client.addEventListener('credentialsrequired', () => finish({ status: 'error' }));
        client.addEventListener('securityfailure', () => finish({ status: 'error' }));
        attempt.disconnect = () => client.disconnect();
      } else {
        finish({ status: 'error' });
      }
    } catch (error) {
      if (apiErrorObject(error)?.code === 'desktop_busy') {
        finish({ status: 'busy', role });
      } else {
        finish({ status: 'error', message: formatApiErrorDetail(error) });
      }
    }
  }

  function disconnect() {
    dispose();
    setState({ status: 'idle' });
  }

  return { state, vnc, picture, connect, disconnect };
}
