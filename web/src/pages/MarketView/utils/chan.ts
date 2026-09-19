/**
 * 缠论几何：K线包含处理 → 分型 → 笔 → 中枢 → 买卖点。
 *
 * 为什么单独放一个模块：缠论的每一步都有自己的判定规则，而且**每一步都能悄悄错**——
 * 包含方向取反、分型隔位不够、笔不交替，画出来的图仍然"看着像缠论"，但结论全错。
 * 所以这里全是纯函数，阶段之间只传数据，便于逐段单测。
 *
 * 口径采用缠中说禅原文的常见工程化实现，取舍都写在各自函数上；有争议的地方
 * 一律选择**保守**（宁可少画一条笔，不画一条不成立的）。
 */

/** 原始K线。`time` 是 unix 秒（与 lightweight-charts 的 Time 一致）。 */
export interface ChanBar {
  time: number;
  high: number;
  low: number;
}

/** 包含处理后的K线。`index` 指回原始数组下标——渲染时要落到真实K线上。 */
export interface MergedBar {
  index: number;
  high: number;
  low: number;
}

export type FractalKind = 'top' | 'bottom';

/** 分型：包含处理后的三根K线里，中间那根的高低价同时最高/最低。 */
export interface ChanFractal {
  kind: FractalKind;
  /** 中间K线在**原始**数组里的下标（落点用它）。 */
  index: number;
  time: number;
  price: number;
}

/** 笔：连接一个顶分型与一个底分型。 */
export interface ChanStroke {
  from: ChanFractal;
  to: ChanFractal;
  direction: 'up' | 'down';
}

/** 中枢：至少三段连续笔的重叠区间。 */
export interface ChanZhongshu {
  /** 区间 [low, high]——由前三个笔段的重叠计算而来。 */
  low: number;
  high: number;
  /** 起点/终点时间（用于渲染矩形横向范围）。 */
  startTime: number;
  endTime: number;
  /** 参与该中枢的笔段下标范围（闭区间）。 */
  fromStroke: number;
  toStroke: number;
}

export interface ChanGeometry {
  merged: MergedBar[];
  fractals: ChanFractal[];
  strokes: ChanStroke[];
  zhongshu: ChanZhongshu[];
  points: ChanPoint[];
}

/** 买卖点。只做最常见、也最可判定的一/二/三类买点与对应卖点。 */
export interface ChanPoint {
  kind: 'buy1' | 'buy2' | 'buy3' | 'sell1' | 'sell2' | 'sell3';
  time: number;
  price: number;
}

/**
 * 包含处理（缠论第一步）。
 *
 * 两根K线互为包含时（一根的高低区间含住另一根，**含边界相等**），
 * 向上取高高（高点取大、低点取大），向下取低低（高点取小、低点取小）。
 *
 * 方向必须是**持久状态**，不能每步用"已合并序列的最后两根"去推 —— 那在只合并出
 * 一根时没有参照，只能回退到原始数据瞎猜，实测会把方向算反（于是高低取错，后续
 * 分型全错）。这里按原文做法记 `direction` 并只更新它：
 *
 * - 两根不构成包含 → 用它们的相对位置更新方向（都上移=up，都下移=down）
 * - 包含且方向已知 → 按方向合并
 * - 包含且方向未知（序列开头）→ 先用两根的**中心**相对位置定方向，再合并
 *
 * 保守之处：方向完全无从判断（两根高低全等）时按"向上取高高"处理并保持
 * 确定性——同样输入必得同样输出；原文对这种情况没有硬规定，不声称唯一正确。
 */
export function mergeInclusions(bars: ChanBar[]): MergedBar[] {
  const out: MergedBar[] = [];
  let direction: 'up' | 'down' | null = null;

  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i];
    if (!out.length) {
      out.push({ index: i, high: bar.high, low: bar.low });
      continue;
    }
    const prev = out[out.length - 1];
    const contains = (bar.high <= prev.high && bar.low >= prev.low)
      || (bar.high >= prev.high && bar.low <= prev.low);
    if (!contains) {
      if (bar.high > prev.high && bar.low > prev.low) direction = 'up';
      else if (bar.high < prev.high && bar.low < prev.low) direction = 'down';
      out.push({ index: i, high: bar.high, low: bar.low });
      continue;
    }
    if (direction === null) {
      // 只看包含的两根无法判方向，用中心相对位置定一次
      const prevMid = (prev.high + prev.low) / 2;
      const curMid = (bar.high + bar.low) / 2;
      direction = curMid >= prevMid ? 'up' : 'down';
    }
    if (direction === 'down') {
      prev.high = Math.min(prev.high, bar.high);
      prev.low = Math.min(prev.low, bar.low);
    } else {
      prev.high = Math.max(prev.high, bar.high);
      prev.low = Math.max(prev.low, bar.low);
    }
    // index 保持不动：合并后的K线画在**最初**那根的位置，避免连续同向包含时
    // 落点漂移到区间外
  }
  return out;
}

/**
 * 分型识别。**两个方向都是两个条件同时成立**（原文：顶分型"顶最高"、
 * 底分型"底最低"，各自连高低都要求是极值）：
 *
 * - 顶分型：`b.high > a.high && b.high > c.high && b.low > a.low && b.low > c.low`
 * - 底分型：`b.low < a.low && b.low < c.low && b.high < a.high && b.high < c.high`
 *
 * 严格不等，**相等不算分型**（相等意味着并列，此时分型不成立，强行认定会造出假笔）。
 * 底分型那半边的第二组条件曾经写成 `b.high > ...`（方向写反），后果是底分型几乎
 * 永远检不出来——图上只剩顶分型，笔全断在半路，而"看着还有几根线"极易被忽略。
 */
export function findFractals(merged: MergedBar[], bars: ChanBar[]): ChanFractal[] {
  const out: ChanFractal[] = [];
  for (let i = 1; i < merged.length - 1; i++) {
    const a = merged[i - 1];
    const b = merged[i];
    const c = merged[i + 1];
    if (b.high > a.high && b.high > c.high && b.low > a.low && b.low > c.low) {
      out.push({ kind: 'top', index: b.index, time: bars[b.index].time, price: b.high });
    } else if (b.low < a.low && b.low < c.low && b.high < c.high && b.high < a.high) {
      out.push({ kind: 'bottom', index: b.index, time: bars[b.index].time, price: b.low });
    }
  }
  return out;
}

/** 一笔至少要跨越的K线根数（原口径"分型之间至少隔一根"，故下标差 ≥ 4）。 */
export const MIN_STROKE_GAP = 4;

/**
 * 笔的生成。规则（保守版，顺序即优先级）：
 * 1. 同类型分型相邻 → 保留更极端者（顶取更高、底取更低）
 * 2. 异类型但**距离不足** `MIN_STROKE_GAP` → 丢弃后者
 * 3. 顶分型不高于前一个底 / 底分型不低于前一个顶 → 丢弃（方向不成立）
 * 4. 通过者才成一笔，且顶底必须交替
 */
export function buildStrokes(fractals: ChanFractal[]): ChanStroke[] {
  const picked: ChanFractal[] = [];
  for (const f of fractals) {
    const last = picked[picked.length - 1];
    if (!last) {
      picked.push(f);
      continue;
    }
    if (f.kind === last.kind) {
      // 同类：留更极端的那根
      const better = f.kind === 'top' ? f.price > last.price : f.price < last.price;
      if (better) picked[picked.length - 1] = f;
      continue;
    }
    if (f.index - last.index < MIN_STROKE_GAP) continue;     // 距离不足
    const ok = f.kind === 'top' ? f.price > last.price : f.price < last.price;
    if (!ok) continue;                                        // 方向不成立
    picked.push(f);
  }

  const strokes: ChanStroke[] = [];
  for (let i = 1; i < picked.length; i++) {
    strokes.push({
      from: picked[i - 1],
      to: picked[i],
      direction: picked[i].kind === 'top' ? 'up' : 'down',
    });
  }
  return strokes;
}

/**
 * 中枢识别。取连续三段笔，它们的区间交集非空即为中枢：
 * `high = min(三段高点)`、`low = max(三段低点)`。随后**延伸**：只要后续笔
 * 仍与该区间有重叠，就并入同一个中枢（原文的中枢延伸）。
 *
 * 保守之处：只输出**不重叠**的中枢（新中枢必须完全脱离前一个区间），
 * 避免同一段行情被画成多个中枢造成视觉噪声与错误结论。
 */
export function findZhongshu(strokes: ChanStroke[]): ChanZhongshu[] {
  const out: ChanZhongshu[] = [];
  let i = 0;
  while (i + 2 < strokes.length) {
    const seg = [strokes[i], strokes[i + 1], strokes[i + 2]];
    const highs = seg.map((s) => Math.max(s.from.price, s.to.price));
    const lows = seg.map((s) => Math.min(s.from.price, s.to.price));
    const high = Math.min(...highs);
    const low = Math.max(...lows);
    if (!(high > low)) {                 // 无重叠 → 不是中枢，右移一段
      i += 1;
      continue;
    }
    let end = i + 2;
    while (end + 1 < strokes.length) {
      const next = strokes[end + 1];
      const nHigh = Math.max(next.from.price, next.to.price);
      const nLow = Math.min(next.from.price, next.to.price);
      if (nHigh < low || nLow > high) break;   // 完全脱离 → 中枢结束
      end += 1;
    }
    out.push({
      low,
      high,
      startTime: strokes[i].from.time,
      endTime: strokes[end].to.time,
      fromStroke: i,
      toStroke: end,
    });
    i = end + 1;
  }
  return out;
}

/**
 * 买卖点。只判定**有明确规则、不靠形态想象**的三类：
 *
 * - 一类买点：下跌笔的底分型，且该底低于前一个底（创新低背驰位置的近似）
 * - 二类买点：一类买点之后，回抽不破前低的那一底
 * - 三类买点：向上离开中枢后的回抽，低点仍在中枢上沿之上
 *
 * 对称地给出对应卖点。**不做背驰判定**——那需要 MACD 面积等额外输入，
 * 这里没有，硬凑出来的"背驰"最容易自欺，所以不画。
 */
export function findPoints(
  strokes: ChanStroke[],
  zhongshu: ChanZhongshu[],
): ChanPoint[] {
  const out: ChanPoint[] = [];
  const bottoms = strokes.filter((s) => s.to.kind === 'bottom').map((s) => s.to);
  const tops = strokes.filter((s) => s.to.kind === 'top').map((s) => s.to);

  // 一类：底/顶依次更低/更高
  bottoms.forEach((b, i) => {
    if (i > 0 && b.price < bottoms[i - 1].price) {
      out.push({ kind: 'buy1', time: b.time, price: b.price });
    }
  });
  tops.forEach((t, i) => {
    if (i > 0 && t.price > tops[i - 1].price) {
      out.push({ kind: 'sell1', time: t.time, price: t.price });
    }
  });
  // 二类：一类之后那个不破新低的底（不破新高的顶）
  bottoms.forEach((b, i) => {
    if (i > 0 && b.price >= bottoms[i - 1].price
      && i > 1 && bottoms[i - 1].price < bottoms[i - 2].price) {
      out.push({ kind: 'buy2', time: b.time, price: b.price });
    }
  });
  tops.forEach((t, i) => {
    if (i > 0 && t.price <= tops[i - 1].price
      && i > 1 && tops[i - 1].price > tops[i - 2].price) {
      out.push({ kind: 'sell2', time: t.time, price: t.price });
    }
  });
  // 三类：离开中枢后的回抽不回到中枢内
  for (const z of zhongshu) {
    for (const s of strokes) {
      if (s.from.time < z.endTime) continue;
      if (s.to.kind === 'bottom' && s.to.price > z.high) {
        out.push({ kind: 'buy3', time: s.to.time, price: s.to.price });
      }
      if (s.to.kind === 'top' && s.to.price < z.low) {
        out.push({ kind: 'sell3', time: s.to.time, price: s.to.price });
      }
    }
  }
  return out;
}

/** 一条链跑完：K线 → 包含处理 → 分型 → 笔 → 中枢 → 买卖点。 */
export function computeChan(bars: ChanBar[]): ChanGeometry {
  const clean = bars.filter((b) => Number.isFinite(b.high) && Number.isFinite(b.low));
  if (clean.length < 5) {
    return { merged: [], fractals: [], strokes: [], zhongshu: [], points: [] };
  }
  const merged = mergeInclusions(clean);
  const fractals = findFractals(merged, clean);
  const strokes = buildStrokes(fractals);
  const zhongshu = findZhongshu(strokes);
  const points = findPoints(strokes, zhongshu);
  return { merged, fractals, strokes, zhongshu, points };
}
