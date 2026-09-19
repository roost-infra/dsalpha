/**
 * 因子衰减曲线几何的单测。
 *
 * 取向和 chan.test.ts / indicators.test.ts 一致：钉住**画错了也看不出来**的地方。
 * 一条 `NaN` 路径在浏览器里是被整条丢弃的（polyline 直接不渲染），表现出"这条
 * 因子没有数据"，而不是"代码算错了"——所以这几条边界必须逐条钉住。
 */
import { describe, expect, it } from 'vitest';

import type { IcPoint } from '@/api/factors';

import { buildIcCurve, formatIcDate, maxAbsIc, niceIcBound, zeroLine } from '../icCurve';

const CFG = { width: 100, height: 40, padTop: 4, padBottom: 4, bound: 0.05 };

const series = (pairs: Array<[string, number, number?]>): IcPoint[] =>
  pairs.map(([date, ic, n]) => (n === undefined ? { date, ic } : { date, ic, n }));

describe('formatIcDate', () => {
  it('用 UTC 构造，避免负时区把日期显示成前一天', () => {
    // 断言不依赖 CI 机器的语言：显式指定 locale。
    // 若实现走 `new Date("2025-01-02")` + 本地格式化，UTC-8 会显示成 Jan 1。
    expect(formatIcDate('2025-01-02', 'en-US')).toContain('Jan');
    expect(formatIcDate('2025-01-02', 'en-US')).toContain('2');
    expect(formatIcDate('2025-01-02', 'en-US')).not.toContain('1,');
  });

  it('各语言下都给出同一个日号（不因 locale 漂移）', () => {
    const zh = formatIcDate('2025-01-02', 'zh-CN');
    const en = formatIcDate('2025-01-02', 'en-US');
    expect(zh).toContain('2');
    expect(en).toContain('2');
    expect(zh).not.toBe(en); // 确实用了传入的 locale
  });

  it('非 ISO 输入原样返回，不抛异常', () => {
    expect(formatIcDate('2025/01/02')).toBe('2025/01/02');
    expect(formatIcDate('')).toBe('');
    expect(formatIcDate('garbage')).toBe('garbage');
  });

  it('月末/年末不被时区推成上一天或下一天', () => {
    expect(formatIcDate('2025-01-01', 'en-US')).toContain('Jan 1');
    expect(formatIcDate('2025-12-31', 'en-US')).toContain('Dec 31');
  });
});

describe('niceIcBound', () => {
  it('把幅度抬到可读的档位，且永不返回 0（零高域会毁掉整条路径）', () => {
    expect(niceIcBound(0)).toBe(0.01);
    expect(niceIcBound(0.003)).toBe(0.01);
    expect(niceIcBound(0.011)).toBe(0.02);
    expect(niceIcBound(0.02)).toBe(0.02);   // 边界值取自身
    expect(niceIcBound(0.021)).toBe(0.03);
    expect(niceIcBound(0.5)).toBe(0.5);
  });

  it('非有限输入退回最小档而不是 NaN', () => {
    expect(niceIcBound(NaN)).toBe(0.01);
    expect(niceIcBound(Infinity)).toBe(0.01);
    expect(niceIcBound(-1)).toBe(0.01);
  });

  it('超出档位表时向上取整到 0.1', () => {
    expect(niceIcBound(1.24)).toBe(1.3);
    expect(niceIcBound(2)).toBe(2);
  });
});

describe('maxAbsIc', () => {
  it('跨多条序列取最大绝对值，忽略非有限值', () => {
    expect(maxAbsIc([series([['2025-01-02', -0.03]]), series([['2025-01-03', 0.07]])])).toBeCloseTo(0.07, 10);
    expect(maxAbsIc([series([['2025-01-02', NaN]]), series([['2025-01-03', 0.02]])])).toBeCloseTo(0.02, 10);
  });

  it('空输入返回 0（交给 niceIcBound 兜底）', () => {
    expect(maxAbsIc([])).toBe(0);
    expect(maxAbsIc([undefined, []])).toBe(0);
  });
});

describe('buildIcCurve', () => {
  it('空 / 全非法序列返回空结果而不是 NaN 路径', () => {
    for (const input of [undefined, [], series([['2025-01-02', NaN]])]) {
      const c = buildIcCurve(input, CFG);
      expect(c.path).toBe('');
      expect(c.points).toEqual([]);
      expect(c.single).toBe(false);
    }
  });

  it('单点返回空路径但标记 single，并把点放在水平中央', () => {
    const c = buildIcCurve(series([['2025-01-02', 0.03]]), CFG);
    expect(c.single).toBe(true);
    expect(c.path).toContain('M');          // 单点也有 d，方便画圆点用
    expect(c.points).toHaveLength(1);
    expect(c.points[0].x).toBeCloseTo(CFG.width / 2, 10);
  });

  it('跳过 null 后 x 轴按**压缩后**的下标均分，不留下错位的空档', () => {
    // 中间那天缺值：剩下两个点应当落在 0 和 width，而不是 0 和 width/2
    const c = buildIcCurve(
      series([['2025-01-02', 0.01], ['2025-01-03', NaN], ['2025-01-06', 0.02]]),
      CFG,
    );
    expect(c.points.map((p) => p.x)).toEqual([0, CFG.width]);
    expect(c.points.map((p) => p.ic)).toEqual([0.01, 0.02]);
  });

  it('IC 为 0 落在中线上（零有意义，不能被当成缺值丢掉）', () => {
    const c = buildIcCurve(series([['2025-01-02', 0], ['2025-01-03', 0]]), CFG);
    expect(c.points).toHaveLength(2);
    for (const p of c.points) expect(p.y).toBeCloseTo(p.zeroY, 10);
  });

  it('域对称：+bound 贴顶、-bound 贴底', () => {
    const c = buildIcCurve(series([['a', 0.05], ['b', -0.05]]), CFG);
    expect(c.points[0].y).toBeCloseTo(CFG.padTop, 6);
    expect(c.points[1].y).toBeCloseTo(CFG.height - CFG.padBottom, 6);
  });

  it('超出域的值被夹住，路径不会画到框外', () => {
    const c = buildIcCurve(series([['a', 5], ['b', -5]]), CFG);
    const lo = CFG.padTop;
    const hi = CFG.height - CFG.padBottom;
    for (const p of c.points) {
      expect(p.y).toBeGreaterThanOrEqual(lo - 1e-9);
      expect(p.y).toBeLessThanOrEqual(hi + 1e-9);
    }
  });

  it('退化的域（0 / NaN / 负）不会产生 NaN 路径', () => {
    for (const bound of [0, NaN, -1]) {
      const c = buildIcCurve(series([['a', 0.01], ['b', 0.02]]), { ...CFG, bound });
      expect(c.path).not.toContain('NaN');
      expect(c.points.every((p) => Number.isFinite(p.y))).toBe(true);
    }
  });

  it('域或尺寸非法时返回空结果而不是抛异常', () => {
    expect(buildIcCurve(series([['a', 0.01]]), { ...CFG, width: 0 }).path).toBe('');
    expect(buildIcCurve(series([['a', 0.01]]), { ...CFG, height: 2, padTop: 4, padBottom: 4 }).path).toBe('');
  });

  it('peak 取绝对值最大的那天（负 IC 同样是信号）', () => {
    const c = buildIcCurve(series([['a', 0.02], ['b', -0.05], ['c', 0.03]]), CFG);
    expect(c.peak).toEqual({ date: 'b', ic: -0.05 });
  });

  it('meanN 只统计带 n 的点', () => {
    const c = buildIcCurve(series([['a', 0.01, 100], ['b', 0.02], ['c', 0.03, 300]]), CFG);
    expect(c.meanN).toBeCloseTo(200, 10);
    expect(buildIcCurve(series([['a', 0.01]]), CFG).meanN).toBeNull();
  });

  it('路径以 M 开头、含与点数相同的顶点数', () => {
    const c = buildIcCurve(series([['a', 0.01], ['b', -0.02], ['c', 0.03]]), CFG);
    expect(c.path.startsWith('M')).toBe(true);
    expect(c.path.match(/[ML]/g)?.length).toBe(3);
  });
});

describe('zeroLine', () => {
  it('位于绘图区垂直中点，且两端是有限的 drawable 段', () => {
    const { y, path } = zeroLine(CFG);
    expect(y).toBeCloseTo(CFG.padTop + (CFG.height - CFG.padTop - CFG.padBottom) / 2, 10);
    expect(path).not.toContain('NaN');
  });
});
