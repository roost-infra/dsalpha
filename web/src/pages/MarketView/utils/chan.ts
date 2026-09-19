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

/** 线段：由至少三笔构成、方向独立于其中单笔走势的更大级别段。 */
export interface ChanSegment {
  direction: 'up' | 'down';
  /** 段起/止落在的笔端点上（与笔共用分型，渲染时直接连线）。 */
  fromTime: number;
  fromPrice: number;
  toTime: number;
  toPrice: number;
  /** 该段覆盖的笔下标区间（闭区间）。 */
  fromStroke: number;
  toStroke: number;
}

export interface ChanGeometry {
  merged: MergedBar[];
  fractals: ChanFractal[];
  strokes: ChanStroke[];
  segments: ChanSegment[];
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
 * 线段（笔之上的级别）。
 *
 * **为什么不能"三笔重叠"了事**：那样单边行情会被切成一堆碎线段，而线段的定义恰恰是
 * "方向独立于其中单笔走势的更大级别段"。
 *
 * 判据用的是**同向极值被反向突破**：向上段里某个向下笔的低点跌破段内此前最低点，
 * 上升结构即告破坏，段在**那个低点**结束；向下段对称。等价说法是"线段结束于转折处"，
 * 因此段的终点落在极值上、渲染时能与笔的端点直接连起来。
 *
 * 关于原文的**特征序列法**：那是更精确的做法（把笔折成特征序列、在序列上找分型）。
 * 本实现试过，但特征序列的包含处理我做得不对——错拿"笔的价格区间"当特征元素的包含
 * 判据，而相邻笔的区间本来就必然重叠，结果整个序列被压成一个元素、线段恒为空。
 * 与其留一个半懂的原文版，这里选一个**行为可验证**的等价判据，并把差异写在这里。
 * 若将来要补回特征序列法，必须同时实现"特征序列的第一、二种情况"，否则同样会退化。
 *
 * 另一个取舍：不足 `MIN_SEGMENT_STROKES`（3 笔）的残段**并入上一段**而不是丢掉——
 * 丢掉会在图上留一段没有线段的空白，看起来像 bug。
 */
export const MIN_SEGMENT_STROKES = 3;

export function buildSegments(strokes: ChanStroke[]): ChanSegment[] {
  if (strokes.length < MIN_SEGMENT_STROKES) return [];

  const out: ChanSegment[] = [];
  let dir: 'up' | 'down' = strokes[0].direction;
  let segStart = 0;
  /** 段内前一档同类极值：向上段看上一个底，向下段看上一个顶。 */
  let lastExtreme: number | null = null;

  const closeSegment = (endStroke: number): void => {
    const tail = strokes[endStroke];
    out.push({
      direction: dir,
      fromTime: strokes[segStart].from.time,
      fromPrice: strokes[segStart].from.price,
      toTime: tail.to.time,
      toPrice: tail.to.price,
      fromStroke: segStart,
      toStroke: endStroke,
    });
  };

  for (let i = 0; i < strokes.length; i++) {
    const s = strokes[i];

    // 段结束判据：**同类极值不再朝原方向推进**
    //   向上段：下一个底**抬高**（higher low）→ 上升力度衰竭，段在**那个底**结束
    //   向下段：下一个顶**降低**（lower high）→ 下降力度衰竭，段在**那个顶**结束
    //   且该段已满 `MIN_SEGMENT_STROKES` 笔（不满足就继续累积）
    //
    // 为什么不是"跌破前低"：那是**趋势反转**的判据，比线段大一级；用它会让整个
    // 上升行情（每次回撤都在抬高）合成一条线段 —— 实测 420 根K线/11 笔只切出 1 条，
    // 等于没切。抬高/降低才是线段级别该看的力度变化。
    // `MIN_SEGMENT_STROKES` 是硬约束：不满足就**只更新极值、不切段**。
    // 少了它，连续抬高的低点会把一段上升行情切成每笔一段（实测 11 笔切出 3 段以上），
    // 那已经不是"级别"而是噪声。
    const enough = i - segStart + 1 >= MIN_SEGMENT_STROKES;
    if (dir === 'up' && s.to.kind === 'bottom') {
      if (enough && lastExtreme !== null && s.to.price > lastExtreme) {
        closeSegment(i);
        dir = 'down';
        segStart = i;
        lastExtreme = null;
        continue;
      }
      lastExtreme = lastExtreme === null ? s.to.price : Math.min(lastExtreme, s.to.price);
    } else if (dir === 'down' && s.to.kind === 'top') {
      if (enough && lastExtreme !== null && s.to.price < lastExtreme) {
        closeSegment(i);
        dir = 'up';
        segStart = i;
        lastExtreme = null;
        continue;
      }
      lastExtreme = lastExtreme === null ? s.to.price : Math.max(lastExtreme, s.to.price);
    }
  }

  // 收尾：循环结束时若还有未闭合的段就闭合它。**不能只在"已经形成过段"时才收** ——
  // 单边行情里一次破坏都没有，那样整段走势一条线段都画不出来（实测过）。
  if (out[out.length - 1]?.toStroke !== strokes.length - 1) {
    out.push({
      direction: dir,
      fromTime: strokes[segStart].from.time,
      fromPrice: strokes[segStart].from.price,
      toTime: strokes[strokes.length - 1].to.time,
      toPrice: strokes[strokes.length - 1].to.price,
      fromStroke: segStart,
      toStroke: strokes.length - 1,
    });
  }
  return out;
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
 * 买卖点。**这是启发式标注，不是缠论的背驰判定**——先把边界说清楚：
 *
 * - 一类买点：下跌笔的底分型，且该底低于前一个底
 * - 二类买点：一类买点之后，回抽不破前低的那一底
 * - 三类买点：向上离开中枢后的回抽，低点仍在中枢上沿之上
 *
 * 对称地给出对应卖点。
 *
 * ⚠️ **没有背驰判定**。原文的一类买卖点要求在**背驰**处（趋势力度衰竭），而背驰
 * 需要 MACD 面积/均线面积等额外输入——本模块只拿到 K 线高低价，算不出来。所以这里的
 * "一类"退化成"创新低/新高"，后果是**标注会比真正的背驰点多得多**：普通的新低也会
 * 被标成 B1。视觉上它是一张"摆动极值图"，不是一张"该买该卖图"。
 *
 * 之所以仍然内置：它在中枢前后有参考价值（B3/S3 的定义是硬的），而把"没有的东西"
 * 硬凑出来（比如自己瞎算一个 MACD 面积）比少画更容易误导。UI 上默认关闭，也是这个
 * 原因——要看得懂再开。
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

/** 一条链跑完：K线 → 包含处理 → 分型 → 笔 → 线段 → 中枢 → 买卖点。 */
export function computeChan(bars: ChanBar[]): ChanGeometry {
  const clean = bars.filter((b) => Number.isFinite(b.high) && Number.isFinite(b.low));
  if (clean.length < 5) {
    return { merged: [], fractals: [], strokes: [], segments: [], zhongshu: [], points: [] };
  }
  const merged = mergeInclusions(clean);
  const fractals = findFractals(merged, clean);
  const strokes = buildStrokes(fractals);
  const segments = buildSegments(strokes);
  const zhongshu = findZhongshu(strokes);
  const points = findPoints(strokes, zhongshu);
  return { merged, fractals, strokes, segments, zhongshu, points };
}
