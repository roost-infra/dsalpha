import type { Metric, Observation, Quarter } from './quarterData';

const comparisonFields = ['current', 'previous', 'year_ago'] as const;
type Translate = (key: string) => string;

function download(data: Blob, filename: string) {
  const url = URL.createObjectURL(data);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export function exportBrief(quarter: Quarter, t: Translate, percent: (value: number | null) => string) {
  const lines = [
    `# ${quarter.symbol} ${t('research.title')}`, '',
    `${quarter.company} | ${quarter.selected.end} | ${quarter.currency}`, '',
    `[${quarter.selected.form}](${quarter.selected.url}) · ${quarter.selected.filed}`, '',
    `${t('research.retrievedAt')} · ${quarter.fetched_at}`, '',
  ];
  for (const reason of quarter.uncertainty ?? []) lines.push(t(`research.${reason}`), '');
  for (const metric of quarter.metrics) {
    lines.push(`## ${t(`research.metrics.${metric.key}`)}`, '',
      `${metric.current.value.toLocaleString('en-US')} ${quarter.currency} · ${t('research.yoy')} ${percent(metric.yoy)} · ${t('research.qoq')} ${percent(metric.qoq)}`, '');
    for (const field of comparisonFields) {
      const observation = metric[field];
      if (!observation) continue;
      lines.push(`- ${t(`research.${field}`)} · ${observation.value.toLocaleString('en-US')} ${quarter.currency} · ${t(`research.${observation.method}`)}`);
      for (const fact of observation.evidence) {
        lines.push(`  - ${fact.sign < 0 ? '− ' : '+ '}${fact.value.toLocaleString('en-US')} ${quarter.currency} · ${fact.start} – ${fact.end} · ${fact.filed} · ${fact.accession} · [${fact.form} ${fact.tag}](${fact.url})`);
      }
    }
    for (const reason of metric.uncertainty ?? []) lines.push(t(`research.${reason}`));
    lines.push('');
  }
  download(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }), `${quarter.symbol}-${quarter.selected.end}.md`);
}

export async function exportWorkbook(quarter: Quarter, t: Translate) {
  const { default: ExcelJS } = await import('exceljs');
  const workbook = new ExcelJS.Workbook();
  const comparisons = workbook.addWorksheet('Quarter');
  const evidence = workbook.addWorksheet('SEC Facts');
  const metadata = workbook.addWorksheet('Source');
  comparisons.addRow([quarter.symbol, quarter.company, quarter.selected.end, quarter.currency]);
  comparisons.addRow([t('research.metric'), ...comparisonFields.map((field) => t(`research.${field}`)), t('research.qoq'), t('research.yoy')]);
  evidence.addRow(['Metric', 'Comparison', 'Operator', 'USD', 'Tag', 'Start', 'End', 'Filed', 'Accession', 'Source', 'Method']);
  metadata.addRows([
    ['Ticker', quarter.symbol],
    ['Company', quarter.company],
    ['Reporting period', quarter.selected.end],
    ['Currency', quarter.currency],
    ['Filed', quarter.selected.filed],
    ['Accession', quarter.selected.accession],
    ['Filing', { text: quarter.selected.form, hyperlink: quarter.selected.url }],
    ['Retrieved at (UTC)', quarter.fetched_at],
  ]);
  for (const reason of quarter.uncertainty ?? []) metadata.addRow(['Uncertainty', t(`research.${reason}`)]);
  for (const metric of quarter.metrics) {
    for (const reason of metric.uncertainty ?? []) metadata.addRow([metric.key, t(`research.${reason}`)]);
  }
  metadata.getColumn(1).width = 24;
  metadata.getColumn(2).width = 36;

  function evidenceFormula(metric: Metric, field: typeof comparisonFields[number], value: Observation | null) {
    if (!value) return null;
    if (value.evidence.length === 0) return value.value;
    const start = evidence.rowCount + 1;
    for (const fact of value.evidence) {
      evidence.addRow([metric.key, field, fact.sign, fact.value, fact.tag, fact.start, fact.end,
        fact.filed, fact.accession, { text: fact.form, hyperlink: fact.url }, value.method]);
    }
    const end = evidence.rowCount;
    return { formula: `SUMPRODUCT('SEC Facts'!C${start}:C${end},'SEC Facts'!D${start}:D${end})`, result: value.value };
  }

  for (const metric of quarter.metrics) {
    const row = comparisons.addRow([t(`research.metrics.${metric.key}`), ...comparisonFields.map((field) => evidenceFormula(metric, field, metric[field]))]);
    for (const [source, output, change] of [['C', 'E', metric.qoq], ['D', 'F', metric.yoy]] as const) {
      const base = `${source}${row.number}`;
      row.getCell(output).value = { formula: `IF(OR(ISBLANK(${base}),${base}<=0),"",B${row.number}/${base}-1)`, result: change ?? '' };
    }
  }
  comparisons.getRow(2).font = { bold: true };
  comparisons.getColumn(1).width = 26;
  for (const column of ['B', 'C', 'D']) {
    comparisons.getColumn(column).width = 24;
    comparisons.getColumn(column).numFmt = '#,##0';
  }
  for (const column of ['E', 'F']) comparisons.getColumn(column).numFmt = '0.0%';
  evidence.getRow(1).font = { bold: true };
  for (const [column, width] of Object.entries({ A: 24, B: 14, D: 20, E: 66, F: 14, G: 14, H: 14, I: 24, K: 16 })) {
    evidence.getColumn(column).width = width;
  }
  const file = (await workbook.xlsx.writeBuffer()) as ArrayBuffer;
  download(new Blob([file], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), `${quarter.symbol}-${quarter.selected.end}.xlsx`);
}
