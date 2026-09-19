/**
 * 缠论画线的 lightweight-charts v4 series primitive。
 *
 * 照 `SelectionPrimitive` / `AgentAnnotationsPrimitive` 的写法：`attached()` 拿
 * chart+series，`paneViews()` 返回分层视图，`draw()` 里用
 * `timeScale.timeToCoordinate()` 与 `series.priceToCoordinate()` 把时间/价格换成
 * 像素——因此**每次 pan/zoom 都会重算**，不需要我们自己处理视口变化。
 *
 * 分层：中枢矩形填色放 `bottom`（压在K线下面），笔线与买卖点放 `top`（盖在上面）。
 * 这样矩形不会挡住K线，而笔线始终可见。
 *
 * 视觉上刻意与两种既有标注区分开：用户框选是**青色**、agent 画的是**石板蓝**，
 * 缠论用**琥珀色**——三者同时出现在图上时不会互相误读。
 */
import type {
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesPrimitivePaneViewZOrder,
  SeriesAttachedParameter,
  Time,
  IChartApiBase,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';

import type { ChanGeometry, ChanFractal, ChanPoint, ChanZhongshu } from './chan';

export type ChanTheme = 'light' | 'dark';

/** 各层开关。分型默认关：真实行情里它们太密，全开会糊成一片。 */
export interface ChanLayers {
  strokes: boolean;
  zhongshu: boolean;
  fractals: boolean;
  points: boolean;
}

export const DEFAULT_CHAN_LAYERS: ChanLayers = {
  strokes: true,
  zhongshu: true,
  fractals: false,
  points: false,
};

/** 与用户框选（青）、agent 标注（石板蓝）区分开的琥珀色。 */
const COLOR = {
  light: {
    stroke: 'rgba(190, 120, 20, 0.95)',
    zhongshuFill: 'rgba(190, 120, 20, 0.10)',
    zhongshuBorder: 'rgba(190, 120, 20, 0.55)',
    fractal: 'rgba(150, 95, 15, 0.9)',
    point: 'rgba(160, 30, 30, 0.95)',
    label: 'rgba(90, 60, 10, 0.95)',
  },
  dark: {
    stroke: 'rgba(240, 175, 80, 0.95)',
    zhongshuFill: 'rgba(240, 175, 80, 0.12)',
    zhongshuBorder: 'rgba(240, 175, 80, 0.55)',
    fractal: 'rgba(240, 190, 120, 0.9)',
    point: 'rgba(255, 120, 120, 0.95)',
    label: 'rgba(255, 220, 170, 0.95)',
  },
} as const;

interface SeriesLike {
  priceToCoordinate(price: number): number | null;
}

interface TimeScaleLike {
  timeToCoordinate(time: Time): number | null;
}

/** 分型落点：顶取高点、底取低点——画在K线实际极值上。 */
export function fractalPrice(f: ChanFractal): number {
  return f.price;
}

/**
 * 纯几何：把中枢按价格与时间换成矩形（媒体坐标）。
 *
 * 抽成独立函数是为了**可测**——直接断言 `draw()` 里的 canvas 调用也能测，但矩形
 * 的四个边界（左右取时间、上下取价格）算错时画出来只是"位置略偏"，比直接断言
 * 数值难发现得多。
 */
export function zhongshuRect(
  z: ChanZhongshu,
  timeScale: TimeScaleLike,
  series: SeriesLike,
): { left: number; top: number; width: number; height: number } | null {
  const x1 = timeScale.timeToCoordinate(z.startTime as unknown as Time);
  const x2 = timeScale.timeToCoordinate(z.endTime as unknown as Time);
  const yHigh = series.priceToCoordinate(z.high);
  const yLow = series.priceToCoordinate(z.low);
  if (x1 === null || x2 === null || yHigh === null || yLow === null) return null;
  const left = Math.min(x1, x2);
  return {
    left,
    top: Math.min(yHigh, yLow),
    width: Math.abs(x2 - x1),
    height: Math.abs(yLow - yHigh),
  };
}

/**
 * 纯几何：把一笔换成线段端点。
 *
 * 两端都取**价格坐标**而不是收盘价——缠论的笔连接的是分型的高低点，
 * 用收盘价会让线头缩进K线体内，转折点读不出来。
 */
export function strokeSegment(
  from: ChanFractal,
  to: ChanFractal,
  timeScale: TimeScaleLike,
  series: SeriesLike,
): { x1: number; y1: number; x2: number; y2: number } | null {
  const x1 = timeScale.timeToCoordinate(from.time as unknown as Time);
  const x2 = timeScale.timeToCoordinate(to.time as unknown as Time);
  const y1 = series.priceToCoordinate(fractalPrice(from));
  const y2 = series.priceToCoordinate(fractalPrice(to));
  if (x1 === null || x2 === null || y1 === null || y2 === null) return null;
  return { x1, y1, x2, y2 };
}

/** 买卖点的标签文案（图上直接画，所以是字面量不是 i18n key）。 */
const POINT_LABEL: Record<ChanPoint['kind'], string> = {
  buy1: 'B1', buy2: 'B2', buy3: 'B3',
  sell1: 'S1', sell2: 'S2', sell3: 'S3',
};

export class ChanPrimitive {
  private _geometry: ChanGeometry | null = null;
  private _layers: ChanLayers = DEFAULT_CHAN_LAYERS;
  private _theme: ChanTheme = 'dark';
  private _chart: IChartApiBase<Time> | null = null;
  private _series: SeriesLike | null = null;
  private _requestUpdate: (() => void) | null = null;

  attached(param: SeriesAttachedParameter<Time>): void {
    this._chart = param.chart as IChartApiBase<Time>;
    this._series = param.series as unknown as SeriesLike;
    this._requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
  }

  setGeometry(geometry: ChanGeometry | null): void {
    this._geometry = geometry;
    this._requestUpdate?.();
  }

  setLayers(layers: ChanLayers): void {
    this._layers = layers;
    this._requestUpdate?.();
  }

  setTheme(theme: ChanTheme): void {
    this._theme = theme;
    this._requestUpdate?.();
  }

  updateAllViews(): void {}

  paneViews(): ISeriesPrimitivePaneView[] {
    const source = this;
    return [
      {
        zOrder(): SeriesPrimitivePaneViewZOrder {
          return 'bottom';
        },
        renderer(): ISeriesPrimitivePaneRenderer {
          return {
            draw(target: CanvasRenderingTarget2D): void {
              source._drawZhongshu(target);
            },
          };
        },
      },
      {
        zOrder(): SeriesPrimitivePaneViewZOrder {
          return 'top';
        },
        renderer(): ISeriesPrimitivePaneRenderer {
          return {
            draw(target: CanvasRenderingTarget2D): void {
              source._drawStrokes(target);
              source._drawFractals(target);
              source._drawPoints(target);
            },
          };
        },
      },
    ];
  }

  private _scale(): { timeScale: TimeScaleLike; series: SeriesLike } | null {
    if (!this._chart || !this._series) return null;
    return { timeScale: this._chart.timeScale() as unknown as TimeScaleLike, series: this._series };
  }

  private _drawZhongshu(target: CanvasRenderingTarget2D): void {
    const geo = this._geometry;
    const scale = this._scale();
    if (!geo || !scale || !this._layers.zhongshu || geo.zhongshu.length === 0) return;
    const c = COLOR[this._theme];
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      for (const z of geo.zhongshu) {
        const box = zhongshuRect(z, scale.timeScale, scale.series);
        if (!box || box.width <= 0 || box.height <= 0) continue;
        ctx.save();
        ctx.fillStyle = c.zhongshuFill;
        ctx.fillRect(box.left, box.top, box.width, box.height);
        ctx.strokeStyle = c.zhongshuBorder;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.strokeRect(box.left, box.top, box.width, box.height);
        ctx.restore();
      }
    });
  }

  private _drawStrokes(target: CanvasRenderingTarget2D): void {
    const geo = this._geometry;
    const scale = this._scale();
    if (!geo || !scale || !this._layers.strokes || geo.strokes.length === 0) return;
    const c = COLOR[this._theme];
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      ctx.save();
      ctx.strokeStyle = c.stroke;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([]);
      for (const s of geo.strokes) {
        const seg = strokeSegment(s.from, s.to, scale.timeScale, scale.series);
        if (!seg) continue;
        ctx.beginPath();
        ctx.moveTo(seg.x1, seg.y1);
        ctx.lineTo(seg.x2, seg.y2);
        ctx.stroke();
      }
      ctx.restore();
    });
  }

  private _drawFractals(target: CanvasRenderingTarget2D): void {
    const geo = this._geometry;
    const scale = this._scale();
    if (!geo || !scale || !this._layers.fractals || geo.fractals.length === 0) return;
    const c = COLOR[this._theme];
    const R = 3;
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      ctx.save();
      ctx.fillStyle = c.fractal;
      for (const f of geo.fractals) {
        const x = scale.timeScale.timeToCoordinate(f.time as unknown as Time);
        const y = scale.series.priceToCoordinate(fractalPrice(f));
        if (x === null || y === null) continue;
        // 顶分型画在价格上方、底分型画在下方 —— 不要盖住K线极值
        const cy = f.kind === 'top' ? y - R - 2 : y + R + 2;
        ctx.beginPath();
        ctx.moveTo(x, cy - R);
        ctx.lineTo(x + R, cy + R);
        ctx.lineTo(x - R, cy + R);
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();
    });
  }

  private _drawPoints(target: CanvasRenderingTarget2D): void {
    const geo = this._geometry;
    const scale = this._scale();
    if (!geo || !scale || !this._layers.points || geo.points.length === 0) return;
    const c = COLOR[this._theme];
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      ctx.save();
      ctx.strokeStyle = c.point;
      ctx.fillStyle = c.label;
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 3]);
      ctx.font = '11px ui-sans-serif, system-ui, sans-serif';
      for (const p of geo.points) {
        const x = scale.timeScale.timeToCoordinate(p.time as unknown as Time);
        const y = scale.series.priceToCoordinate(p.price);
        if (x === null || y === null) continue;
        const isBuy = p.kind.startsWith('buy');
        // 买点在下方、卖点在上方，并画一小段引线指向价格
        const yLabel = isBuy ? y + 14 : y - 14;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x, isBuy ? y + 8 : y - 8);
        ctx.stroke();
        ctx.fillText(POINT_LABEL[p.kind], x - 8, yLabel);
      }
      ctx.restore();
    });
  }
}
