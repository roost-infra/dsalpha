/**
 * 缠论几何的单测。重点是**边界与保守性**，不是"能算出点东西"：
 *
 * - 包含处理的方向（向上取高高 / 向下取低低）
 * - 分型严格不等（并列不算分型）
 * - 笔的交替、最小间隔、同类分型取极端
 * - 中枢的重叠判定与延伸
 * - 数据不足时返回空集而不是抛异常
 *
 * 这些点每一条错了，图上仍然"看着像缠论"，但结论全错——所以逐条钉住。
 */
import { describe, expect, it } from 'vitest';

import {
  buildStrokes,
  computeChan,
  findFractals,
  findZhongshu,
  mergeInclusions,
  MIN_STROKE_GAP,
  type ChanBar,
  type ChanFractal,
} from '../chan';

const bar = (time: number, high: number, low: number): ChanBar => ({ time, high, low });

/** 把 [high, low] 序列转成 K线数组（时间自增）。 */
const barsOf = (pairs: Array<[number, number]>): ChanBar[] =>
  pairs.map(([high, low], i) => bar(1000 + i * 60, high, low));

describe('mergeInclusions', () => {
  it('upward containment takes the higher high AND the higher low', () => {
    // 前两根都上移 → direction=up；第三根被上一根包含 → 取高高
    const merged = mergeInclusions(barsOf([
      [10, 8], [12, 10],   // up: high/low both rise
      [11.5, 10.5],        // contained by [12,10] → high=max(12,11.5), low=max(10,10.5)
    ]));
    expect(merged).toHaveLength(2);
    expect(merged[1].high).toBe(12);
    expect(merged[1].low).toBe(10.5);
  });

  it('downward containment takes the lower high AND the lower low', () => {
    const merged = mergeInclusions(barsOf([
      [12, 10], [10, 8],   // down
      [9.5, 8.5],          // contained by [10,8] → high=min(10,9.5), low=min(8,8.5)
    ]));
    // 第三根被**第二根(10,8)**含住（不是第一根）：向下取低低
    // → high=min(10,9.5)=9.5、low=min(8,8.5)=8
    expect(merged).toHaveLength(2);
    expect(merged[1].high).toBe(9.5);
    expect(merged[1].low).toBe(8);
  });

  it('keeps every bar when none is contained', () => {
    // 三根依次上移，两两都不构成包含
    const merged = mergeInclusions(barsOf([[10, 8], [12, 10], [14, 12]]));
    expect(merged).toHaveLength(3);
  });

  it('keeps the merged bar anchored at the first bar of the run', () => {
    const merged = mergeInclusions(barsOf([
      [10, 8], [12, 10],
      [11.5, 10.5], [11.2, 10.2],   // 连续被包含
    ]));
    // 连续包含都合到同一根上，index 停在最初那根 → 落点不漂移
    expect(merged[1].index).toBe(1);
    expect(merged[1].high).toBe(12);
    expect(merged[1].low).toBe(10.5);
  });
});

describe('findFractals', () => {
  it('requires strict inequality on both high and low', () => {
    // 中间那根高点并列最高 → 不是顶分型
    const merged = mergeInclusions(barsOf([
      [10, 8], [12, 10], [12, 11],
    ]));
    expect(findFractals(merged, barsOf([[10, 8], [12, 10], [12, 11]]))).toHaveLength(0);
  });

  it('finds a top fractal', () => {
    const pairs: Array<[number, number]> = [[9, 7], [12, 10], [10, 8]];
    const merged = mergeInclusions(barsOf(pairs));
    const fx = findFractals(merged, barsOf(pairs));
    expect(fx).toHaveLength(1);
    expect(fx[0].kind).toBe('top');
    expect(fx[0].price).toBe(12);
  });

  it('finds a bottom fractal', () => {
    const pairs: Array<[number, number]> = [[10, 9], [9, 6], [11, 9]];
    const merged = mergeInclusions(barsOf(pairs));
    const fx = findFractals(merged, barsOf(pairs));
    expect(fx).toHaveLength(1);
    expect(fx[0].kind).toBe('bottom');
    expect(fx[0].price).toBe(6);
  });
});

describe('buildStrokes', () => {
  const fx = (kind: 'top' | 'bottom', index: number, price: number): ChanFractal =>
    ({ kind, index, price, time: 1000 + index * 60 });

  it('alternates top/bottom and drops too-close fractals', () => {
    const strokes = buildStrokes([
      fx('bottom', 0, 10),
      fx('top', 2, 12),        // 距离 2 < MIN_STROKE_GAP → 丢弃
      fx('top', 6, 15),        // 同类且更极端 → 保留
      fx('bottom', 12, 11),    // 距离 6 ≥ 4 且更低？11 > 10 → 方向不成立，丢
      fx('bottom', 14, 9),     // 更低 → 成立
    ]);
    // picked = 底0 → 顶6（顶2 被同类替换掉）→ 底14；底12 因方向不成立被丢
    expect(strokes).toHaveLength(2);
    expect(strokes[0].direction).toBe('up');
    expect(strokes[0].from.price).toBe(10);
    expect(strokes[0].to.price).toBe(15);
    expect(strokes[1].direction).toBe('down');
    expect(strokes[1].to.price).toBe(9);
  });

  it('keeps the more extreme fractal when two of the same kind are adjacent', () => {
    const strokes = buildStrokes([
      fx('bottom', 0, 10),
      fx('top', 6, 12),
      fx('top', 10, 18),        // 同类更高 → 顶被替换成 18
      fx('bottom', 20, 9),
    ]);
    expect(strokes).toHaveLength(2);
    expect(strokes[0].to.price).toBe(18);

    // 反向：同类更低的顶不该替换
    const strokes2 = buildStrokes([
      fx('bottom', 0, 10),
      fx('top', 6, 12),
      fx('top', 10, 11),        // 更低 → 丢弃
      fx('bottom', 20, 9),
    ]);
    expect(strokes2[0].to.price).toBe(12);
  });

  it('MIN_STROKE_GAP is the documented 4', () => {
    expect(MIN_STROKE_GAP).toBe(4);
  });
});

describe('findZhongshu', () => {
  it('needs overlapping ranges across three consecutive strokes', () => {
    const mk = (a: number, b: number, t: number) => ({
      from: { kind: 'bottom' as const, index: 0, time: t, price: a },
      to: { kind: 'top' as const, index: 1, time: t + 60, price: b },
      direction: 'up' as const,
    });
    // 三段都覆盖 [10, 14] → 中枢
    const zs = findZhongshu([mk(10, 16, 100), mk(12, 20, 200), mk(11, 15, 300)]);
    expect(zs).toHaveLength(1);
    expect(zs[0].low).toBe(12);   // max(10,12,11)
    expect(zs[0].high).toBe(15);  // min(16,20,15)

    // 第二段与其它不重叠 → 无中枢
    const none = findZhongshu([mk(10, 12, 100), mk(30, 40, 200), mk(11, 15, 300)]);
    expect(none).toHaveLength(0);
  });

  it('returns nothing for fewer than three strokes', () => {
    expect(findZhongshu([])).toHaveLength(0);
  });
});

describe('computeChan', () => {
  it('returns empty geometry (never throws) when there is not enough data', () => {
    expect(computeChan([])).toEqual({
      merged: [], fractals: [], strokes: [], zhongshu: [], points: [],
    });
    expect(computeChan(barsOf([[10, 8], [11, 9]])).strokes).toHaveLength(0);
  });

  it('ignores bars with non-finite high/low instead of producing NaN geometry', () => {
    const dirty = [...barsOf([[10, 8], [12, 10], [11, 9], [13, 11], [12, 10]]),
      { time: 9999, high: Number.NaN, low: Number.NaN }];
    const geo = computeChan(dirty);
    expect(geo.merged.every((m) => Number.isFinite(m.high) && Number.isFinite(m.low))).toBe(true);
  });

  it('produces an alternating stroke chain when enough swing exists', () => {
    // 造一段明显的上下摆动：每 5 根一个转折
    const pairs: Array<[number, number]> = [];
    let base = 10;
    for (let leg = 0; leg < 8; leg++) {
      const dir = leg % 2 === 0 ? 1 : -1;
      for (let k = 0; k < 5; k++) {
        base += dir * 1.0;
        pairs.push([base + 1, base - 1]);
      }
    }
    const geo = computeChan(barsOf(pairs));
    for (let i = 1; i < geo.strokes.length; i++) {
      expect(geo.strokes[i].direction).not.toBe(geo.strokes[i - 1].direction);
      expect(geo.strokes[i].from).toBe(geo.strokes[i - 1].to);
    }
  });
});
