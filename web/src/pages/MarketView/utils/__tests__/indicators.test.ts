/**
 * 指标算法层单测。和 chan.test.ts 同样的取向：钉住**最容易写错又看不出来**的地方，
 * 而不是"能返回一串数字"。
 *
 * 重点：
 *  - 预热区必须是 null，不能是 0/NaN（否则图上会画出一条贴地的假线）
 *  - 全长度对齐：返回数组与输入 K 线逐位对应（i 对应第 i 根）
 *  - BOLL 用**总体**标准差（除以 n），不是样本标准差（n-1）
 *  - ATR 用 Wilder 平滑（首值取前 period 个 TR 的算术平均）
 *  - MACD 的 signal 是 MACD 线的 EMA，只在有效 MACD 值上递推并对齐回原始下标
 *  - R 倍数投影的方向推断、以及退化输入（entry==stop）返回 null
 *
 * 期望值由独立实现（Python）算出后写死，不是按 TS 实现反推的。
 */
import { describe, expect, it } from 'vitest';

import {
  calculateATR,
  calculateBollinger,
  calculateEMA,
  calculateMACD,
  calculateSMA,
  lastValid,
  projectRiskLevels,
  riskPositionSize,
  type Bar,
} from '../indicators';

const CLOSES = [20, 20, 20, 22, 21, 23, 24, 23, 25, 26, 25, 27, 28, 27, 29];
const HIGHS = [21, 20, 20, 22, 21, 23, 24, 23, 25, 26, 25, 27, 28, 27, 29];
const LOWS = [19, 20, 20, 19, 20, 21, 22, 22, 23, 25, 24, 25, 26, 25, 28];

const BARS: Bar[] = CLOSES.map((close, i) => ({
  time: 1000 + i,
  open: close,
  high: HIGHS[i],
  low: LOWS[i],
  close,
  volume: 100 + i,
}));

const values = (pts: Array<{ value: number | null }>) => pts.map((p) => p.value);

describe('calculateEMA', () => {
  it('预热区返回 null，首值用前 period 个的 SMA 播种', () => {
    const ema = calculateEMA(BARS, 2);
    expect(values(ema)[0]).toBeNull();
    expect(values(ema)[1]).toBeCloseTo(20, 10);
    // EMA_2 = 20 + (20-20)*2/3 = 20
    expect(values(ema)[2]).toBeCloseTo(20, 10);
    expect(values(ema)[3]).toBeCloseTo(21.3333, 3);
    expect(values(ema)[14]).toBeCloseTo(28.3846, 3);
  });

  it('保持全长度对齐（时间戳与输入逐位一致）', () => {
    const ema = calculateEMA(BARS, 5);
    expect(ema).toHaveLength(BARS.length);
    ema.forEach((p, i) => expect(p.time).toBe(BARS[i].time));
    // 前 4 个是预热
    expect(values(ema).slice(0, 4).every((v) => v === null)).toBe(true);
    expect(values(ema)[4]).not.toBeNull();
  });

  it('数据不足或非法周期时返回对齐的 null 序列而不是抛异常', () => {
    expect(values(calculateEMA(BARS.slice(0, 2), 5)).every((v) => v === null)).toBe(true);
    expect(calculateEMA(BARS, 0)).toEqual([]);
    expect(calculateEMA([], 14)).toEqual([]);
  });
});

describe('calculateSMA', () => {
  it('滑动窗口正确且用 null 表示预热', () => {
    const sma = calculateSMA(BARS, 3);
    expect(values(sma).slice(0, 2)).toEqual([null, null]);
    expect(values(sma)[2]).toBeCloseTo((20 + 20 + 20) / 3, 10);
    expect(values(sma)[3]).toBeCloseTo((20 + 20 + 22) / 3, 10);
    expect(values(sma)[4]).toBeCloseTo((20 + 22 + 21) / 3, 10);
  });

  it('支持自定义取值函数（例如典型价）', () => {
    const sma = calculateSMA(BARS, 2, (b) => (b.high + b.low + b.close) / 3);
    expect(values(sma)[1]).toBeCloseTo((20 + 20) / 2, 10);
  });
});

describe('calculateBollinger', () => {
  it('用总体标准差（除以 n），不是样本标准差（n-1）', () => {
    // 取一段方差明显的窗口，手工算总体标准差
    const window = BARS.slice(0, 5); // closes 20,20,20,22,21
    const period = 5;
    const mean = (20 + 20 + 20 + 22 + 21) / 5; // 20.6
    const popVar = [20, 20, 20, 22, 21]
      .map((c) => (c - mean) ** 2)
      .reduce((a, b) => a + b, 0) / period;
    const popSd = Math.sqrt(popVar);
    const sampleSd = Math.sqrt(
      [20, 20, 20, 22, 21].map((c) => (c - mean) ** 2).reduce((a, b) => a + b, 0) /
        (period - 1),
    );
    expect(sampleSd).not.toBeCloseTo(popSd, 6); // 前提：两者确实可区分

    const bb = calculateBollinger(window, period, 2);
    expect(values(bb.middle)[4]).toBeCloseTo(mean, 10);
    expect(values(bb.upper)[4]).toBeCloseTo(mean + 2 * popSd, 10);
    expect(values(bb.lower)[4]).toBeCloseTo(mean - 2 * popSd, 10);
  });

  it('中轨等于同周期 SMA，且上下轨关于中轨对称', () => {
    const bb = calculateBollinger(BARS, 5, 2);
    const sma = calculateSMA(BARS, 5);
    for (let i = 4; i < BARS.length; i++) {
      expect(values(bb.middle)[i]).toBeCloseTo(values(sma)[i]!, 10);
      const up = values(bb.upper)[i]!;
      const lo = values(bb.lower)[i]!;
      expect(up - values(bb.middle)[i]!).toBeCloseTo(values(bb.middle)[i]! - lo, 10);
    }
  });

  it('恒定价格时上下轨收敛到该价格（方差为 0）', () => {
    const flat: Bar[] = Array.from({ length: 6 }, (_, i) => ({
      time: i,
      high: 50,
      low: 50,
      close: 50,
    }));
    const bb = calculateBollinger(flat, 5, 2);
    expect(values(bb.upper)[5]).toBeCloseTo(50, 10);
    expect(values(bb.lower)[5]).toBeCloseTo(50, 10);
  });

  it('预热区为 null，数据不足时不抛异常', () => {
    const bb = calculateBollinger(BARS, 20);
    expect(values(bb.middle).every((v) => v === null)).toBe(true);
    expect(bb.period).toBe(20);
    expect(bb.stdDev).toBe(2);
  });
});

describe('calculateMACD', () => {
  it('signal 只在有效 MACD 值上递推，并正确对齐回原始下标', () => {
    // fast=2, slow=3, signal=2 → MACD 从下标 2 起有效；signal 需要 2 个有效 MACD，
    // 故首个 signal 落在下标 3。这是最容易整体错位一位的地方。
    const r = calculateMACD(BARS, 2, 3, 2);
    const macd = values(r.macd);
    const signal = values(r.signal);
    const hist = values(r.histogram);

    expect(macd[0]).toBeNull();
    expect(macd[1]).toBeNull();
    expect(macd[2]).not.toBeNull();

    expect(signal[2]).toBeNull(); // 只有 1 个有效 MACD，还不够 2 个
    expect(signal[3]).not.toBeNull();
    expect(signal[1]).toBeNull();

    // hist = macd - signal，且只有 signal+x 都存在时才有值
    for (let i = 0; i < BARS.length; i++) {
      if (macd[i] === null || signal[i] === null) {
        expect(hist[i]).toBeNull();
      } else {
        expect(hist[i]).toBeCloseTo(macd[i]! - signal[i]!, 10);
      }
    }
  });

  it('默认参数下预热与 (slow, signal) 的先后关系正确', () => {
    const long: Bar[] = Array.from({ length: 60 }, (_, i) => ({
      time: i,
      high: 100 + i,
      low: 99 + i,
      close: 99.5 + i,
    }));
    const r = calculateMACD(long); // 12, 26, 9
    const macd = values(r.macd);
    const signal = values(r.signal);

    expect(macd[24]).toBeNull(); // slow EMA 未就绪
    expect(macd[25]).not.toBeNull(); // 第 26 根起
    expect(signal.slice(0, 33).every((v) => v === null)).toBe(true); // 26-1 + 9-1 = 33
    expect(signal[33]).not.toBeNull();
    expect(r.macd).toHaveLength(long.length);
  });

  it('单调上涨时 MACD 与 signal 均为正，hist 收敛', () => {
    const up: Bar[] = Array.from({ length: 80 }, (_, i) => ({
      time: i,
      high: 10 + i,
      low: 9 + i,
      close: 9.8 + i,
    }));
    const r = calculateMACD(up);
    expect(lastValid(r.macd)!).toBeGreaterThan(0);
    expect(lastValid(r.signal)!).toBeGreaterThan(0);
  });

  it('空输入与非法周期返回对齐的空/ null 序列', () => {
    expect(calculateMACD([], 12, 26, 9).macd).toEqual([]);
    expect(values(calculateMACD(BARS, 0, 26, 9).macd).every((v) => v === null)).toBe(true);
  });
});

describe('calculateATR', () => {
  it('复现 Wilder 平滑序列（期望值取自独立实现）', () => {
    const atr = calculateATR(BARS, 5);
    const v = values(atr);
    // 首 4 根预热
    expect(v.slice(0, 4)).toEqual([null, null, null, null]);
    expect(v[4]).toBeCloseTo(1.4, 6);
    expect(v[5]).toBeCloseTo(1.52, 6);
    expect(v[6]).toBeCloseTo(1.616, 6);
    expect(v[7]).toBeCloseTo(1.6928, 6);
    expect(v[8]).toBeCloseTo(1.75424, 6);
    // 第 10 根 TR 掉到 1，ATR 必须跟着下降 —— 抓"忘记用 TR 而是用 high-low"之类
    expect(v[9]).toBeCloseTo(1.603392, 6);
    expect(v[14]).toBeCloseTo(2.030039, 6);
  });

  it('真实波幅包含跳空（gap），不只是 high-low', () => {
    // 第一根 10-11（prevClose 只有在该根之后才参与）。
    // 第二根整体跳空到 20-21：TR1 = max(1, |21-10.5|=10.5, |20-10.5|=9.5) = 10.5。
    // 若实现只看 high-low 会得到 1 —— 断言值能区分这两种实现。
    const gap: Bar[] = [
      { time: 0, high: 11, low: 10, close: 10.5 },
      { time: 1, high: 21, low: 20, close: 20.5 },
    ];
    const atr = calculateATR(gap, 2);
    expect(values(atr)[1]).toBeCloseTo((1 + 10.5) / 2, 10);
    // 反向确认：不能是"只算 high-low"的结果
    expect(values(atr)[1]).not.toBeCloseTo((1 + 1) / 2, 6);
  });

  it('恒定区间时 ATR 收敛到该区间宽度', () => {
    const flat: Bar[] = Array.from({ length: 10 }, (_, i) => ({
      time: i,
      high: 101,
      low: 99,
      close: 100,
    }));
    const v = values(calculateATR(flat, 3));
    for (let i = 2; i < 10; i++) expect(v[i]).toBeCloseTo(2, 10);
  });

  it('数据不足或非法周期时返回对齐的 null 序列', () => {
    expect(values(calculateATR(BARS.slice(0, 3), 5)).every((v) => v === null)).toBe(true);
    expect(values(calculateATR(BARS, 0))).toEqual([]);
  });
});

describe('lastValid', () => {
  it('取最后一个非 null 值，全 null 时返回 null', () => {
    expect(lastValid([{ time: 0, value: 1 }, { time: 1, value: null }])).toBe(1);
    expect(lastValid([{ time: 0, value: null }])).toBeNull();
    expect(lastValid([])).toBeNull();
  });
});

describe('projectRiskLevels', () => {
  it('多头：止损在入场下方，目标按 R 倍数向上', () => {
    const p = projectRiskLevels(100, 98, [1, 2, 3])!;
    expect(p.side).toBe('long');
    expect(p.risk).toBeCloseTo(2, 10);
    expect(p.levels.map((l) => l.r)).toEqual([1, 2, 3]);
    expect(p.levels.map((l) => l.price)).toEqual([102, 104, 106]);
    expect(p.stopR.price).toBeCloseTo(98, 10);
  });

  it('空头：止损在入场上方，目标按 R 倍数向下', () => {
    const p = projectRiskLevels(100, 103, [2])!;
    expect(p.side).toBe('short');
    expect(p.risk).toBeCloseTo(3, 10);
    expect(p.levels[0].price).toBeCloseTo(94, 10);
  });

  it('显式方向与推断一致时接受', () => {
    const long = projectRiskLevels(100, 98, [1], 'long')!;
    expect(long.side).toBe('long');
    expect(long.levels[0].price).toBeCloseTo(102, 10);

    const short = projectRiskLevels(100, 103, [1], 'short')!;
    expect(short.side).toBe('short');
    expect(short.levels[0].price).toBeCloseTo(97, 10);
  });

  it('显式方向与止损位置矛盾时返回 null（而不是把目标画到止损那一侧）', () => {
    // stop < entry 只能是多头；声称做空说明调用方传错了
    expect(projectRiskLevels(100, 98, [1], 'short')).toBeNull();
    // stop > entry 只能是空头
    expect(projectRiskLevels(100, 103, [1], 'long')).toBeNull();
  });

  it('目标永远在止损的反侧，不会与止损同向', () => {
    for (const [entry, stop] of [
      [100, 98],
      [100, 103],
      [50, 49.5],
      [50, 50.5],
    ]) {
      const p = projectRiskLevels(entry, stop, [1, 2, 3])!;
      const targetsAway = p.levels.every((l) =>
        p.side === 'long' ? l.price > p.entry : l.price < p.entry,
      );
      expect(targetsAway).toBe(true);
      expect(p.stopR.price).toBeCloseTo(p.stop, 10);
    }
  });

  it('entry==stop 或非法输入返回 null（避免除零与无穷目标）', () => {
    expect(projectRiskLevels(100, 100, [1])).toBeNull();
    expect(projectRiskLevels(NaN, 98, [1])).toBeNull();
    expect(projectRiskLevels(100, Infinity, [1])).toBeNull();
  });

  it('过滤非正的 R 倍数', () => {
    const p = projectRiskLevels(100, 98, [0, -1, 2])!;
    expect(p.levels.map((l) => l.r)).toEqual([2]);
  });
});

describe('riskPositionSize', () => {
  it('按风险比例计算仓位', () => {
    // 10 万本金、单笔风险 1%、单位风险 2 元 → 500 股/单位
    expect(riskPositionSize(100000, 0.01, 2)).toBeCloseTo(500, 10);
  });

  it('退化输入返回 null', () => {
    expect(riskPositionSize(0, 0.01, 2)).toBeNull();
    expect(riskPositionSize(100000, 0, 2)).toBeNull();
    expect(riskPositionSize(100000, 0.01, 0)).toBeNull();
    expect(riskPositionSize(NaN, 0.01, 2)).toBeNull();
  });
});
