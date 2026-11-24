import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Monitor } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { ApiError } from '@/api/client';
import { queryKeys } from '@/lib/queryKeys';
import type { Computer } from '@/types/api';

import { getDesktopPreview } from './desktopApi';

function PreviewFrame({ image, label }: { image: Blob; label: string }) {
  const ref = useRef<HTMLImageElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const url = URL.createObjectURL(image);
    ref.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [image]);
  return <img ref={ref} className="absolute inset-0 h-full w-full object-contain" alt={label} />;
}

export function DesktopPreview({ computer }: { computer: Computer }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const desktopReady = computer.status === 'running' && computer.desktop_state === 'ready' && !!computer.desktop_transport;
  const { data, isError } = useQuery({
    queryKey: queryKeys.computers.desktopPreview(
      computer.computer_id, computer.provider_ref ?? null, computer.running_since ?? null,
    ),
    queryFn: ({ signal }) => getDesktopPreview(computer.computer_id, signal),
    enabled: desktopReady && visible,
    refetchInterval: ({ state }) => {
      if (!desktopReady || !visible) return false;
      if (state.error instanceof ApiError) {
        if (state.error.status === 403 || state.error.status === 404) return false;
        if (state.error.retryAfter && state.error.retryAfter > 0) return state.error.retryAfter * 1_000;
      }
      return state.error ? 15_000 : 5_000;
    },
    gcTime: 0,
    retry: false,
  });

  useEffect(() => {
    if (!ref.current) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className="relative grid aspect-video place-items-center overflow-hidden rounded-md border bg-page">
      {desktopReady && visible && data && !isError ? (
        <PreviewFrame image={data} label={t('computer.cloud.previewAlt', { name: computer.name })} />
      ) : (
        <div className="flex flex-col items-center gap-2 text-xs text-muted-foreground">
          <Monitor className="size-6" aria-hidden="true" />
          {t(computer.desktop_transport ? 'computer.cloud.previewUnavailable' : 'computer.cloud.noDesktop')}
        </div>
      )}
    </div>
  );
}
