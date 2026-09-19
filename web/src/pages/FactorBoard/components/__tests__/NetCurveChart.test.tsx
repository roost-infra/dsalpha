/**
 * NetCurveChart 的**接线**测试。
 *
 * 几何逻辑已经有 16 个单测；这里要证明的是"看板真的把这条曲线接上了"：
 * OOS findings 里的两个字段被读到、图例显示两个窗口的终值倍数、两个窗口都空时
 * 整个组件不渲染（老 miner 没有这两个字段，不能画一张空图）。
 *
 * ResponsiveContainer 在 jsdom 里量不到宽高会渲染成空，所以按测试惯例把它 mock
 * 成"直接渲染 children"——我要断言的是自己的图例与取值，不是 recharts 的渲染。
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import type { NetCurvePoint } from '@/api/factors';
import { NetCurveChart } from '../NetCurveChart';

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts');
  return {
    ...actual,
    // 让 children 无论量到多大都渲染出来
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  };
});

const pt = (i: number, value: number, date: string | null = null): NetCurvePoint => ({ i, value, date });

// 8.7e7 / 4.0e7 是生产 report 里真实的量级；倍数取整除值（1.5× / 1.25×），
// 免得这条接线断言同时依赖四舍五入行为——舍入由 formatGrowth 的单测负责。
const MINING = [pt(0, 87_246_569, '2017-01-03'), pt(1, 130_869_853, '2017-01-04')];
const OOS = [pt(0, 40_000_000, '2021-01-04'), pt(1, 50_000_000, '2021-01-05')];

describe('NetCurveChart', () => {
  it('渲染两个窗口的终值倍数（归一化后）', () => {
    render(<NetCurveChart mining={MINING} oos={OOS} />);
    // mining 130869853/87246569 = 1.5×，oos 50000000/40000000 = 1.25×
    expect(screen.getByText(/1\.50×/)).toBeInTheDocument();
    expect(screen.getByText(/1\.25×/)).toBeInTheDocument();
  });

  it('只给一个窗口时仍然渲染，另一个显示占位符', () => {
    render(<NetCurveChart mining={MINING} oos={[]} />);
    expect(screen.getByText(/1\.50×/)).toBeInTheDocument();
    // OOS 缺失 → 1.00× 不能伪造出来，应当是占位符
    expect(screen.getByText(/—/)).toBeInTheDocument();
  });

  it('两个窗口都为空时不渲染任何东西', () => {
    const { container } = render(<NetCurveChart mining={[]} oos={[]} />);
    expect(container).toBeEmptyDOMElement();

    const { container: c2 } = render(<NetCurveChart mining={undefined} oos={undefined} />);
    expect(c2).toBeEmptyDOMElement();
  });

  it('老 miner 只有 mining/oos 标量时（两个曲线字段为 null）不渲染', () => {
    const { container } = render(<NetCurveChart mining={null} oos={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('本组件不自己判长度之外的逻辑 —— 归一化后的两条线共用一根轴', () => {
    // 绝对量级差一倍：若不归一化，小的那条会贴地；这里两条终值都应接近 1
    render(<NetCurveChart mining={[pt(0, 100), pt(1, 200)]} oos={[pt(0, 10000), pt(1, 20000)]} />);
    // 两个图例都显示 2.00×
    expect(screen.getAllByText(/2\.00×/).length).toBe(2);
  });
});
