import { useLayoutEffect, useState, type MouseEventHandler, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';

const KEY_STEP = 24;

interface PanelDividerProps {
  className: string;
  panelId: string;
  width: number;
  containerRef?: RefObject<HTMLElement | null>;
  clampWidth: (width: number) => number;
  onWidthChange: (width: number) => void;
  onMouseDown: MouseEventHandler<HTMLDivElement>;
}

export function PanelDivider({
  className, panelId, width, containerRef, clampWidth, onWidthChange, onMouseDown,
}: PanelDividerProps) {
  const { t } = useTranslation();
  const [bounds, setBounds] = useState<{ min: number; max: number } | null>(null);

  useLayoutEffect(() => {
    const update = () => {
      const min = Math.round(clampWidth(0));
      const max = Math.round(clampWidth(Infinity));
      setBounds((previous) => previous?.min === min && previous.max === max ? previous : { min, max });
    };
    update();
    const container = containerRef?.current;
    const observer = container ? new ResizeObserver(update) : null;
    if (container) observer?.observe(container);
    window.addEventListener('resize', update);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', update);
    };
  }, [clampWidth, containerRef, width]);

  const value = Math.round(width);
  return (
    <div
      className={className}
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={t('filePanel.resize')}
      aria-controls={panelId}
      aria-valuemin={Math.min(value, bounds?.min ?? value)}
      aria-valuemax={Math.max(value, bounds?.max ?? value)}
      aria-valuenow={value}
      onMouseDown={onMouseDown}
      onKeyDown={(event) => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        let desired: number;
        switch (event.key) {
          case 'ArrowLeft': desired = width + KEY_STEP; break;
          case 'ArrowRight': desired = width - KEY_STEP; break;
          case 'Home': desired = 0; break;
          case 'End': desired = Infinity; break;
          default: return;
        }
        event.preventDefault();
        onWidthChange(clampWidth(desired));
      }}
    />
  );
}
