import { describe, expect, it } from 'vitest';
import { codeSpots } from '../codeSpots';

function source(lines: string[]): HTMLElement {
  const root = document.createElement('pre');
  lines.forEach((text, index) => {
    const line = document.createElement('span');
    line.dataset.line = String(index + 1);
    const number = document.createElement('span');
    number.className = 'linenumber';
    number.textContent = String(index + 1);
    const code = document.createElement('span');
    code.textContent = text;
    line.append(number, code);
    line.getBoundingClientRect = () => new DOMRect(0, index * 20, 100, 20);
    root.append(line);
  });
  return root;
}

describe('code line comments', () => {
  it('anchors a clicked line and quotes its code without the gutter', () => {
    const root = source(['def total():', '    return amount']);
    const picker = codeSpots(root).spots!;
    const line = picker.spotAt(root.querySelector('[data-line="2"] span:last-child')!);
    expect(picker.anchorOf([line!])).toEqual({
      kind: 'block', lines: '2', label: 'def total():', quote: 'return amount',
    });
  });

  it('anchors a dragged run and locates it again after an insertion above', () => {
    const original = source(['start()', 'fetch()', 'report()', 'finish()']);
    const picker = codeSpots(original).spots!;
    const lines = picker.spotsIn({ left: 1, top: 21, right: 90, bottom: 59 });
    const anchor = picker.anchorOf(lines);
    expect(anchor).toEqual({ kind: 'block', lines: '2-3', quote: 'fetch() report()' });

    const edited = source(['start()', 'prepare()', 'fetch()', 'report()', 'finish()']);
    const found = codeSpots(edited).find(anchor!);
    expect(found && 'parts' in found ? found.parts[0] : null).toEqual([
      edited.querySelector('[data-line="3"]'),
      edited.querySelector('[data-line="4"]'),
    ]);
  });
});
