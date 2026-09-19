/**
 * 缠论 primitive 的测试。两类断言：
 *
 * 1. **纯几何**（`zhongshuRect` / `strokeSegment`）—— 直接断言数值。矩形四条边
 *    算错时画出来只是"位置略偏"，不测数值很难发现。
 * 2. **绘制调用** —— 用 stub ctx 断言 canvas 调用，与 `selectionPrimitive.test.ts`
 *    同一套做法（真 canvas 在 jsdom 里没有意义）。
 *
 * 另有一条容易忽略但必须钉住的：**坐标换算不到时就跳过**，不能画出 NaN 线
 * （滚出视野的笔如果没被跳掉，会以 (0,0) 为端点拉出一条穿过全图的假线）。
 */
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_CHAN_LAYERS, ChanPrimitive, strokeSegment, zhongshuRect } from '../chanPrimitive';
import { computeChan, type ChanBar, type ChanFractal, type ChanGeometry, type ChanStroke, type ChanZhongshu } from '../chan';

const computeChanForTest = (bars: ChanBar[]) => computeChan(bars);

function makeCtx() {
  return {
    save: vi.fn(), restore: vi.fn(),
    fillRect: vi.fn(), strokeRect: vi.fn(),
    beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
    closePath: vi.fn(), stroke: vi.fn(), fill: vi.fn(),
    setLineDash: vi.fn(), fillText: vi.fn(),
    fillStyle: '', strokeStyle: '', lineWidth: 1, font: '',
  };
}
type Ctx = ReturnType<typeof makeCtx>;

function makeTarget(ctx: Ctx) {
  return {
    useMediaCoordinateSpace(cb: (scope: { context: Ctx; mediaSize: { width: number; height: number } }) => void) {
      cb({ context: ctx, mediaSize: { width: 800, height: 400 } });
    },
  } as never;
}

/** 时间→x 线性、价格→y 反转（价格越高 y 越小），便于手算期望值。 */
// Time 可能是 string|number|BusinessDay，stub 统一按数字处理（测试里只喂数字）
const timeScale = { timeToCoordinate: (t: unknown) => Number(t) / 1000 };
const series = { priceToCoordinate: (p: number) => 400 - p };

function attach(prim: ChanPrimitive, requestUpdate = vi.fn()) {
  prim.attached({ chart: { timeScale: () => timeScale }, series, requestUpdate } as never);
  return requestUpdate;
}

/** 第 index 个 paneView（0 = bottom 填色，1 = top 线）。 */
function drawLayer(prim: ChanPrimitive, index: number, ctx: Ctx) {
  const renderer = prim.paneViews()[index].renderer();
  if (!renderer) throw new Error('expected a renderer');
  renderer.draw(makeTarget(ctx));
}

const fx = (kind: 'top' | 'bottom', index: number, time: number, price: number): ChanFractal =>
  ({ kind, index, time, price });

function geometryWith(partial: Partial<ChanGeometry>): ChanGeometry {
  return { merged: [], fractals: [], strokes: [], zhongshu: [], points: [], ...partial };
}

function stroke(from: ChanFractal, to: ChanFractal): ChanStroke {
  return { from, to, direction: to.kind === 'top' ? 'up' : 'down' };
}

function zhongshuOf(low: number, high: number, startTime: number, endTime: number): ChanZhongshu {
  return { low, high, startTime, endTime, fromStroke: 0, toStroke: 2 };
}

describe('zhongshuRect', () => {
  it('converts price and time into a normalised box', () => {
    const box = zhongshuRect(zhongshuOf(10, 20, 100_000, 300_000), timeScale, series);
    // x: 100..300 ; y: high(20)=380, low(10)=390 → top=380, height=10
    expect(box).toEqual({ left: 100, top: 380, width: 200, height: 10 });
  });

  it('normalises reversed time anchors (end before start)', () => {
    const box = zhongshuRect(zhongshuOf(10, 20, 300_000, 100_000), timeScale, series);
    expect(box).toEqual({ left: 100, top: 380, width: 200, height: 10 });
  });

  it('returns null when either time is off-screen (never draws a NaN box)', () => {
    const partial = { timeToCoordinate: (t: unknown) => (Number(t) > 1e9 ? null : Number(t) / 1000) };
    expect(zhongshuRect(zhongshuOf(10, 20, 2e9, 300_000), partial, series)).toBeNull();
    expect(zhongshuRect(zhongshuOf(10, 20, 100_000, 2e9), partial, series)).toBeNull();
  });

  it('returns null when a price is off-screen', () => {
    const partial = { priceToCoordinate: (p: number) => (p > 100 ? null : 400 - p) };
    expect(zhongshuRect(zhongshuOf(10, 200, 100_000, 300_000), timeScale, partial)).toBeNull();
  });
});

describe('strokeSegment', () => {
  it('anchors ends on the fractal prices, not on closes', () => {
    const seg = strokeSegment(
      fx('bottom', 0, 100_000, 10), fx('top', 5, 300_000, 20), timeScale, series);
    expect(seg).toEqual({ x1: 100, y1: 390, x2: 300, y2: 380 });
  });

  it('returns null if any endpoint is not convertible', () => {
    const partial = { timeToCoordinate: (t: unknown) => (Number(t) > 1e9 ? null : Number(t) / 1000) };
    expect(strokeSegment(fx('bottom', 0, 2e9, 10), fx('top', 5, 300_000, 20), partial, series))
      .toBeNull();
  });
});

describe('ChanPrimitive', () => {
  it('draws nothing without geometry', () => {
    const prim = new ChanPrimitive();
    attach(prim);
    const ctx = makeCtx();
    drawLayer(prim, 0, ctx);
    drawLayer(prim, 1, ctx);
    expect(ctx.fillRect).not.toHaveBeenCalled();
    expect(ctx.stroke).not.toHaveBeenCalled();
  });

  it('draws a dashed box for each zhongshu on the bottom layer', () => {
    const prim = new ChanPrimitive();
    attach(prim);
    prim.setGeometry(geometryWith({ zhongshu: [zhongshuOf(10, 20, 100_000, 300_000)] }));
    const ctx = makeCtx();
    drawLayer(prim, 0, ctx);
    expect(ctx.fillRect).toHaveBeenCalledWith(100, 380, 200, 10);
    expect(ctx.strokeRect).toHaveBeenCalledWith(100, 380, 200, 10);
    expect(ctx.setLineDash).toHaveBeenCalled();
  });

  it('draws one polyline per stroke on the top layer', () => {
    const prim = new ChanPrimitive();
    attach(prim);
    const a = fx('bottom', 0, 100_000, 10);
    const b = fx('top', 5, 300_000, 20);
    prim.setGeometry(geometryWith({ strokes: [stroke(a, b)] }));
    const ctx = makeCtx();
    drawLayer(prim, 1, ctx);
    expect(ctx.moveTo).toHaveBeenCalledWith(100, 390);
    expect(ctx.lineTo).toHaveBeenCalledWith(300, 380);
    expect(ctx.stroke).toHaveBeenCalledTimes(1);
  });

  it('skips strokes whose endpoints cannot be converted', () => {
    const prim = new ChanPrimitive();
    prim.attached({
      chart: { timeScale: () => ({ timeToCoordinate: () => null }) },
      series, requestUpdate: vi.fn(),
    } as never);
    prim.setGeometry(geometryWith({
      strokes: [stroke(fx('bottom', 0, 1, 10), fx('top', 5, 2, 20))],
    }));
    const ctx = makeCtx();
    drawLayer(prim, 1, ctx);
    expect(ctx.moveTo).not.toHaveBeenCalled();
    expect(ctx.stroke).not.toHaveBeenCalled();
  });

  it('honours the layer switches', () => {
    const prim = new ChanPrimitive();
    attach(prim);
    const a = fx('bottom', 0, 100_000, 10);
    const b = fx('top', 5, 300_000, 20);
    prim.setGeometry(geometryWith({
      strokes: [stroke(a, b)],
      zhongshu: [zhongshuOf(10, 20, 100_000, 300_000)],
    }));
    prim.setLayers({ ...DEFAULT_CHAN_LAYERS, strokes: false, zhongshu: false });

    const ctx = makeCtx();
    drawLayer(prim, 0, ctx);
    drawLayer(prim, 1, ctx);
    expect(ctx.fillRect).not.toHaveBeenCalled();
    expect(ctx.stroke).not.toHaveBeenCalled();
  });

  it('keeps fractals and points off by default', () => {
    expect(DEFAULT_CHAN_LAYERS.fractals).toBe(false);
    expect(DEFAULT_CHAN_LAYERS.points).toBe(false);

    const prim = new ChanPrimitive();
    attach(prim);
    prim.setGeometry(geometryWith({
      fractals: [fx('top', 1, 100_000, 30)],
      points: [{ kind: 'buy1', time: 100_000, price: 10 }],
    }));
    const ctx = makeCtx();
    drawLayer(prim, 1, ctx);
    expect(ctx.fill).not.toHaveBeenCalled();
    expect(ctx.fillText).not.toHaveBeenCalled();
  });

  it('draws fractals and points when switched on', () => {
    const prim = new ChanPrimitive();
    attach(prim);
    prim.setGeometry(geometryWith({
      fractals: [fx('top', 1, 100_000, 30)],
      points: [{ kind: 'buy1', time: 100_000, price: 10 }],
    }));
    prim.setLayers({ ...DEFAULT_CHAN_LAYERS, fractals: true, points: true });
    const ctx = makeCtx();
    drawLayer(prim, 1, ctx);
    expect(ctx.fill).toHaveBeenCalledTimes(1);
    expect(ctx.fillText).toHaveBeenCalledWith('B1', 92, 404);
  });

  it('requests a redraw when geometry, layers or theme change', () => {
    const prim = new ChanPrimitive();
    const requestUpdate = attach(prim);
    prim.setGeometry(geometryWith({}));
    prim.setLayers({ ...DEFAULT_CHAN_LAYERS, points: true });
    prim.setTheme('light');
    expect(requestUpdate).toHaveBeenCalledTimes(3);
  });
});

/**
 * 端到端（算法 → 绘制）：用一段有真实形状的K线跑完整条链。
 *
 * 前面的用例都是拿手工构造的几何去测绘制；这条反过来——**让算法自己产出几何**，
 * 再断言图上确实画出了笔与中枢。两者之间的接缝（比如几何算出来了但 layers
 * 没打开、或笔的方向算反导致一条线都没画）只有连起来才看得见。
 */
describe('computeChan → primitive (end-to-end)', () => {
  /** 造一段有明确波段的K线：每 6 根一个方向的腿，交替上下。 */
  function waveBars(legs = 8, legLen = 6): Array<{ time: number; high: number; low: number }> {
    const out: Array<{ time: number; high: number; low: number }> = [];
    let price = 50;
    let t = 1_700_000_000;
    for (let leg = 0; leg < legs; leg++) {
      const dir = leg % 2 === 0 ? 1 : -1;
      for (let k = 0; k < legLen; k++) {
        price += dir * 1.2;
        out.push({ time: t, high: price + 1, low: price - 1 });
        t += 86_400;
      }
    }
    return out;
  }

  it('produces strokes from a wavy series and draws one line per stroke', () => {
    const bars = waveBars();
    const geo = computeChanForTest(bars);
    expect(geo.strokes.length).toBeGreaterThan(0);

    const prim = new ChanPrimitive();
    attach(prim);
    prim.setGeometry(geo);
    const ctx = makeCtx();
    drawLayer(prim, 1, ctx);

    // 每一笔一次 stroke；笔的端点都算得出坐标（时间/价格都在 scale 覆盖范围内）
    expect(ctx.stroke).toHaveBeenCalledTimes(geo.strokes.length);
  });

  it('draws a box for every zhongshu the algorithm finds', () => {
    const geo = computeChanForTest(waveBars());
    const prim = new ChanPrimitive();
    attach(prim);
    prim.setGeometry(geo);
    const ctx = makeCtx();
    drawLayer(prim, 0, ctx);
    expect(ctx.strokeRect).toHaveBeenCalledTimes(geo.zhongshu.length);
  });
});
