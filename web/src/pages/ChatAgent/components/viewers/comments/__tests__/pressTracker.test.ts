import { describe, expect, it, vi } from 'vitest';
import { PressTracker, type PressHost } from '../pressTracker';

function tracker(drawOnTouch: boolean) {
  const area = vi.fn<PressHost['area']>();
  const send = vi.fn<PressHost['send']>();
  const content = document.createElement('div');
  content.getBoundingClientRect = () => new DOMRect(0, 0, 200, 150);
  const view = new PressTracker(content, content, {
    mode: () => true,
    drawOnTouch,
    extending: () => false,
    readKeys: () => {},
    selectsWords: () => false,
    began: () => {},
    dragging: () => {},
    area,
    words: () => {},
    send,
  });
  return { view, area, send };
}

function touch(type: string, x: number, y: number, isPrimary = true) {
  return new PointerEvent(type, {
    pointerType: 'touch',
    pointerId: isPrimary ? 1 : 2,
    isPrimary,
    button: 0,
    buttons: type === 'pointerup' ? 0 : 1,
    clientX: x,
    clientY: y,
  });
}

describe('touch in a file viewer', () => {
  it('draws one image box from the primary touch and suppresses the following click', () => {
    const { view, area } = tracker(true);
    view.down(touch('pointerdown', 10, 20));
    view.down(touch('pointerdown', 1, 2, false));
    view.up(touch('pointerup', 1, 2, false));
    view.move(touch('pointermove', 70, 65));
    view.up(touch('pointerup', 70, 65));

    expect(area).toHaveBeenCalledExactlyOnceWith({
      press: 1, extend: false, x: 10, y: 20,
      box: { left: 10, top: 20, right: 70, bottom: 65 },
    });
    expect(view.click(new MouseEvent('click', { detail: 1 }))).toBeNull();
  });

  it('leaves scrolling to a viewer without touch boxes and still reports a tap', () => {
    const { view, area, send } = tracker(false);
    view.down(touch('pointerdown', 10, 20));
    view.move(touch('pointermove', 70, 65));
    view.cancel();
    expect(area).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();

    view.down(touch('pointerdown', 30, 40));
    view.up(touch('pointerup', 30, 40));
    expect(send).toHaveBeenCalledExactlyOnceWith({ type: 'page:press', press: 1 });
  });
});
