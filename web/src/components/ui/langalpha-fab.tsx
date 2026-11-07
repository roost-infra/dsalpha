import React, { useRef, useCallback, useState, useEffect } from 'react';
import { motion, useMotionValue, useAnimationControls, type PanInfo } from '@/lib/framer';
import { SPRING_DRAG, TWEEN } from '@/lib/motion';

interface LangAlphaFabProps {
  onClick: () => void;
}

const FAB_SIZE = 52;
const EDGE_MARGIN = 12;

/**
 * Draggable floating action button with the LangAlpha logo.
 * Constrained to the lower half of the screen, snaps to nearest edge on release.
 * Tap (not drag) opens the chat input.
 */
function LangAlphaFab({ onClick }: LangAlphaFabProps) {
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const controls = useAnimationControls();
  const isDragging = useRef(false);
  const [bounds, setBounds] = useState({ top: 0, left: 0, right: 0, bottom: 0 });

  // Appear animation on mount. A tween: framer's default for scale is an
  // underdamped spring, which overshoots.
  useEffect(() => {
    controls.start({ scale: 1, opacity: 1, transition: TWEEN.enter });
  }, [controls]);

  // Compute drag bounds: lower half of viewport, above bottom tab bar
  useEffect(() => {
    const update = () => {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const tabHeight = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--bottom-tab-bar') || '78', 10);

      setBounds({
        top: -(vh * 0.4),  // can go up to ~40% from default position
        left: -(vw - FAB_SIZE - EDGE_MARGIN * 2),
        right: 0,
        bottom: -tabHeight,
      });
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  const handleDragStart = useCallback(() => {
    isDragging.current = true;
  }, []);

  const handleDragEnd = useCallback((_: any, _info: PanInfo) => {
    // Snap to nearest horizontal edge
    const vw = window.innerWidth;
    const currentX = x.get();
    // Default position is right: 16px, so x=0 means right edge
    // Negative x means moved left
    const fabCenterX = vw - 16 - FAB_SIZE / 2 + currentX;
    const snapToLeft = fabCenterX < vw / 2;

    const targetX = snapToLeft
      ? -(vw - FAB_SIZE - EDGE_MARGIN * 2)  // snap to left edge
      : 0; // snap back to right edge (default)

    controls.start({
      x: targetX,
      transition: SPRING_DRAG,
    });

    // Small delay so the click handler can check isDragging
    requestAnimationFrame(() => {
      isDragging.current = false;
    });
  }, [x, controls]);

  const handleTap = useCallback(() => {
    if (!isDragging.current) {
      onClick();
    }
  }, [onClick]);

  return (
    <motion.button
      drag
      dragConstraints={bounds}
      dragElastic={0.1}
      dragMomentum={false}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onTap={handleTap}
      animate={controls}
      style={{ x, y }}
      initial={{ scale: 0.6, opacity: 0 }}
      exit={{ scale: 0.6, opacity: 0, transition: TWEEN.exit }}
      className="langalpha-fab"
      aria-label="Open chat"
    >
      <svg
        width="26"
        height="26"
        viewBox="0 0 60 60"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path d="M11 43.5L23.5 30.5L33 37L49 17.5" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="49" cy="17.5" r="5.5" fill="currentColor" />
        <path d="M11 52.5H49" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" opacity="0.28" />
      </svg>
    </motion.button>
  );
}

export default LangAlphaFab;
