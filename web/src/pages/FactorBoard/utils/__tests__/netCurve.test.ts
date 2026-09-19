/**
 * 净值曲线几何层的单测。
 *
 * 这一层的每一种写错都会**画出一条看起来正常但结论相反的图**，所以要逐条钉住：
 *
 *  - 忘了归一化 → 两条曲线差几个数量级，其中一条贴地成直线，看着像"没涨"
 *  - 按数组下标而不是 `i` 合并 → 两条窗口互相错位，OOS 段落进错误的年份
 *  - 首点为 0 时归一化 → Infinity/NaN，整条线被渲染器丢弃（看着像"没数据"）
 *  - 缺值补 0 而不是 null → 凭空多出"回撤到零"的假信号
 */
import { describe, expect, it } from 'vitest';

import type { NetCurvePoint } from '@/api/factors';

import { buildNetCurveData, formatGrowth, rebaseCurve } from '../netCurve';

const pt = (i: number, value: number, date: string | null = null): NetCurvePoint => ({ i, value, date });

describe('rebaseCurve', () => {
  it('以自身首点为 1 归一化', () => {
    expect(rebaseCurve([pt(0, 100), pt(1, 150), pt(2, 50)])).toEqual([1, 1.5, 0.5]);
  });

  it('空输入返回空数组', () => {
    expect(rebaseCurve([])).toEqual([]);
    expect(rebaseCurve(null)).toEqual([]);
    expect(rebaseCurve(undefined)).toEqual([]);
  });

  it('首点若是 qlib 的占位 0，用首个非零值做基准（而不是整条变 null）', () => {
    // 若用 curve[0].value 做基准 → 除以 0 → 整列 null → 图上什么都没有，
    // 与"这个窗口失败了"无法区分。关键断言是后面两个点仍然有效。
    const out = rebaseCurve([pt(0, 0), pt(1, 100), pt(2, 150)]);
    expect(out).toEqual([0, 1, 1.5]);
    expect(out.some((v) => v !== null && !Number.isFinite(v))).toBe(false);
    // 不是"整列 null"
    expect(out.some((v) => v !== null)).toBe(true);
  });

  it('整条全为 0 / 全非法时给等长 null', () => {
    expect(rebaseCurve([pt(0, 0), pt(1, 0)])).toEqual([null, null]);
    expect(rebaseCurve([pt(0, NaN), pt(1, Infinity)])).toEqual([null, null]);
  });

  it('非有限值变成 null（不会污染坐标轴）', () => {
    expect(rebaseCurve([pt(0, 100), pt(1, NaN), pt(2, Infinity)])).toEqual([1, null, null]);
  });
});

describe('buildNetCurveData', () => {
  it('两个窗口共用 trading-day 下标，OOS 落在 mining 的时间轴之内', () => {
    const mining = [pt(0, 100), pt(1, 110), pt(2, 120), pt(3, 130)];
    const oos = [pt(2, 200), pt(3, 210)];
    const d = buildNetCurveData(mining, oos);
    expect(d.rows.map((r) => r.i)).toEqual([0, 1, 2, 3]);
    // OOS 只在 i=2,3 有值，其余为 null（断线而不是连线）
    expect(d.rows.map((r) => r.oos)).toEqual([null, null, 1, 1.05]);
    expect(d.rows.map((r) => r.mining)).toEqual([1, 1.1, 1.2, 1.3]);
  });

  it('按 i 合并而不是按数组位置 —— 起点不同的抽稀序列不会错位', () => {
    // 抽稀后的 mining 首个 i 不是 0；若按位置合并就会整体错位一格
    const mining = [pt(5, 100), pt(9, 200)];
    const oos = [pt(9, 300)];
    const d = buildNetCurveData(mining, oos);
    expect(d.rows.map((r) => r.i)).toEqual([5, 9]);
    expect(d.rows[0].mining).toBe(1);
    expect(d.rows[1].mining).toBe(2);
    expect(d.rows[1].oos).toBe(1);
    expect(d.rows[0].oos).toBeNull();
  });

  it('两个窗口都归一化到各自起点，所以在同一根轴上可比', () => {
    // 绝对量级差 100 倍：若不归一化，小的那条会贴地
    const mining = [pt(0, 100), pt(1, 200)];
    const oos = [pt(1, 10000), pt(2, 20000)];
    const d = buildNetCurveData(mining, oos);
    expect(d.rows[0].mining).toBe(1);
    expect(d.rows[1].mining).toBe(2);
    expect(d.rows[1].oos).toBe(1);
    expect(d.rows[2].oos).toBe(2);
    // 两条终值同量级 → 能画在同一根轴上
    expect(d.miningEnd).toBe(2);
    expect(d.oosEnd).toBe(2);
  });

  it('终值取每列最后一个有限值（不是数组末位）', () => {
    const mining = [pt(0, 100), pt(1, 150)];
    const oos = [pt(1, 10), pt(2, 20), pt(3, NaN)];
    const d = buildNetCurveData(mining, oos);
    // oos 以 10 为基准 → [1, 2, null]；末尾 NaN 不参与，终值取 2
    expect(d.rows.map((r) => r.oos)).toEqual([null, 1, 2, null]);
    expect(d.oosEnd).toBe(2);
    expect(d.miningEnd).toBe(1.5);
  });

  it('空/缺字段时安全退化，不抛异常', () => {
    const empty = { rows: [], miningEnd: null, oosEnd: null, hasDates: false };
    expect(buildNetCurveData([], [])).toEqual(empty);
    expect(buildNetCurveData(null, undefined)).toEqual(empty);
    // 只给一个窗口
    const onlyMining = buildNetCurveData([pt(0, 100), pt(1, 110)], []);
    expect(onlyMining.rows).toHaveLength(2);
    expect(onlyMining.oosEnd).toBeNull();
  });

  it('hasDates 反映日期是否可用（miner 可能退回下标）', () => {
    expect(buildNetCurveData([pt(0, 1, '2021-01-04')], []).hasDates).toBe(true);
    expect(buildNetCurveData([pt(0, 1, null)], []).hasDates).toBe(false);
  });

  it('合并时优先保留真实日期', () => {
    // mining 该行没有日期、oos 有 → 应当采纳 oos 的日期
    const d = buildNetCurveData([pt(3, 100, null)], [pt(3, 50, '2021-06-01')]);
    expect(d.rows[0].date).toBe('2021-06-01');
  });

  it('行按下标升序，即使输入乱序', () => {
    const d = buildNetCurveData([pt(9, 1), pt(2, 1)], [pt(5, 1)]);
    expect(d.rows.map((r) => r.i)).toEqual([2, 5, 9]);
  });

  it('跳过缺 i 或非对象的脏点，而不是整条曲线崩掉', () => {
    const d = buildNetCurveData([pt(0, 100), null as never, pt(1, 110)], []);
    expect(d.rows.map((r) => r.i)).toEqual([0, 1]);
  });
});

describe('formatGrowth', () => {
  it('用倍数而不是百分比', () => {
    expect(formatGrowth(1.42)).toBe('1.42×');
    expect(formatGrowth(1)).toBe('1.00×');
  });

  it('null / 非有限值给占位符', () => {
    expect(formatGrowth(null)).toBe('—');
    expect(formatGrowth(NaN)).toBe('—');
    expect(formatGrowth(Infinity)).toBe('—');
  });
});
