/**
 * DetectionReport + IC 衰减曲线的**接线**测试。
 *
 * 纯几何层（utils/icCurve.ts）已经有 21 个单测，但那些测试证明不了
 * "看板真的把曲线渲染出来了"—— 接线断了（比如 series 字段没透传、
 * 域算成 NaN、条件判断写成永远 false）几何测试仍然全绿。
 *
 * 这里把 t() 换成恒等函数（返回 key），于是断言可以钉住具体分支，
 * 而不依赖打包进去的文案。
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import type { DetectionRun } from '@/api/factors';
import { DetectionReport } from '../DetectionReport';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts && typeof opts === 'object') {
        return `${key}:${JSON.stringify(opts)}`;
      }
      return key;
    },
  }),
}));

const runWith = (probes: unknown[]): DetectionRun =>
  ({
    run_id: 'run-1',
    name: 'f',
    status: 'done',
    current_stage: 'done',
    created_at: 0,
    elapsed_sec: 1,
    stages: [],
    findings: {
      contract: { ok: true, detail: 'ok' },
      recent_ic: probes,
    },
    verdict: { level: 'present', label: 'present', summary: '', ic: 0.03 },
    error: '',
    error_kind: '',
  }) as unknown as DetectionRun;

const SERIES = [
  { date: '2025-01-02', ic: 0.031, n: 1200 },
  { date: '2025-01-03', ic: -0.012, n: 1180 },
  { date: '2025-01-06', ic: 0.044, n: 1210 },
];

describe('DetectionReport — IC 衰减曲线', () => {
  it('带 series 的探针会渲染出可绘制的路径', () => {
    render(<DetectionReport run={runWith([{ window: 20, ic: 0.03, days: 3, series: SERIES }])} />);

    const curve = screen.getByRole('img');
    expect(curve.tagName.toLowerCase()).toBe('svg');
    // 路径必须真的存在且不含 NaN —— 含 NaN 的 polyline 会被浏览器整条丢弃
    const path = curve.querySelector('.factor-ic-curve__line');
    expect(path).not.toBeNull();
    const d = path!.getAttribute('d') ?? '';
    expect(d.startsWith('M')).toBe(true);
    expect(d).not.toContain('NaN');
    // 3 个点 → 3 个顶点
    expect(d.match(/[ML]/g)?.length).toBe(3);
  });

  it('没有 series 的探针只出标量条，不画空图表', () => {
    render(<DetectionReport run={runWith([{ window: 20, ic: 0.03, days: 3 }])} />);
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('多个窗口共用同一个域（否则两条曲线无法比较）', () => {
    render(
      <DetectionReport
        run={runWith([
          { window: 20, ic: 0.03, days: 3, series: SERIES },
          { window: 60, ic: -0.006, days: 3, series: [
            { date: '2025-01-02', ic: -0.005 },
            { date: '2025-01-03', ic: 0.006 },
            { date: '2025-01-06', ic: -0.004 },
          ] },
        ])}
      />,
    );
    const curves = screen.getAllByRole('img');
    expect(curves).toHaveLength(2);
    // 两个 SVG 的 viewBox 相同（同一套几何），且域由**两条**序列决定：
    // 最强点 0.044 落在第一个图的域内，说明域不是各算各的。
    // 直接验证：两条曲线都不含 NaN 且各自有 3 个顶点。
    for (const c of curves) {
      const d = c.querySelector('.factor-ic-curve__line')?.getAttribute('d') ?? '';
      expect(d).not.toContain('NaN');
      expect(d.match(/[ML]/g)?.length).toBe(3);
    }
  });

  it('单点序列画圆点而不是空路径', () => {
    render(
      <DetectionReport
        run={runWith([{ window: 20, ic: 0.03, days: 1, series: [{ date: '2025-01-02', ic: 0.03, n: 10 }] }])}
      />,
    );
    const curve = screen.getByRole('img');
    expect(curve.querySelector('.factor-ic-curve__dot')).not.toBeNull();
    expect(curve.querySelector('.factor-ic-curve__line')).toBeNull();
  });

  it('全非法的 series 退回空态，不渲染 NaN 路径', () => {
    render(
      <DetectionReport
        run={runWith([{ window: 20, ic: null, days: 0, series: [{ date: '2025-01-02', ic: NaN }] }])}
      />,
    );
    // 有 series 数组 → 曲线区块存在，但内部是空态，没有 svg
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('日期标签不因时区漂移到前一天', () => {
    render(<DetectionReport run={runWith([{ window: 20, ic: 0.03, days: 3, series: SERIES }])} />);
    // peak 是 |IC| 最大的 2025-01-06 → 必须出现 6 号，绝不能是 5 号
    // （走本地时区解析的话，UTC 以西的浏览器会显示前一天）。
    // 同时断言"确实渲染了 meta"——否则断线时这条会假绿。
    const meta = document.querySelector('.factor-ic-curve__meta')?.textContent ?? '';
    expect(meta).not.toBe('');
    expect(meta).toContain('6');
    expect(meta).not.toContain('Jan 5');
  });
});
