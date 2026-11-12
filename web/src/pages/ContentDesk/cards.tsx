// @ts-nocheck
import { useMemo } from 'react'

export const STATUS = { idea: '灵感', draft: '初稿', ready: '待发布', published: '已发布' }
export const KINDS = { note: '笔记', link: '链接', quote: '金句', topic: '选题', clip: '素材' }
export const KIND_GLYPH = { note: '✎', link: '↗', quote: '“', topic: '◎', clip: '▧' }
export const STATUS_ORDER = ['idea', 'draft', 'ready', 'published']

function tone(id = '') {
  let n = 0
  for (const ch of String(id)) n = (n * 31 + ch.charCodeAt(0)) % 997
  return n % 6
}

function Glyph({ kind }) {
  return <span className="rcd-glyph" aria-hidden>{KIND_GLYPH[kind] || '✎'}</span>
}

export function IdeaCard({ item, zh, onOpen, onMove }) {
  const date = item.scheduledAt ? item.scheduledAt.slice(0, 10) : ''
  return <article className={`rcd-idea-card is-${item.kind || 'note'} is-${item.status || 'idea'} tone-${tone(item.id)}`} onClick={() => onOpen(item)} tabIndex={0} role="button" onKeyDown={e => { if (e.key === 'Enter') onOpen(item) }}>
    <div className="rcd-idea-art" aria-hidden>
      {item.kind === 'quote' ? <span className="rcd-quote-mark">“</span> : <Glyph kind={item.kind} />}
      <span className="rcd-art-index">{String(item.id || '').slice(-3).toUpperCase()}</span>
    </div>
    <div className="rcd-idea-body">
      <div className="rcd-card-line"><span className="rcd-kind-tag">{KINDS[item.kind] || '灵感'}</span><span className={`rcd-stage is-${item.status}`}>{STATUS[item.status] || item.status}</span></div>
      <h3>{item.title}</h3>
      {item.body && <p>{item.body}</p>}
      <div className="rcd-card-bottom">
        <span>{item.tags?.length ? item.tags.slice(0, 3).map(t => `#${t}`).join(' ') : (zh ? '未分类' : 'Unsorted')}</span>
        <span>{date || item.platform}</span>
      </div>
    </div>
    <div className="rcd-card-hover">
      <button type="button" onClick={e => { e.stopPropagation(); onOpen(item) }}>{zh ? '编辑' : 'Edit'}</button>
      {item.status === 'idea' && <button type="button" onClick={e => { e.stopPropagation(); onMove?.(item, 'draft') }}>{zh ? '转初稿' : 'To draft'}</button>}
    </div>
  </article>
}

export function ContentCard({ item, zh, onOpen, onMove, dragging, onDragStart, onDragEnd }) {
  return <article className={`rcd-content-card is-${item.status} tone-${tone(item.id)} ${dragging ? 'is-dragging' : ''}`} draggable onDragStart={onDragStart} onDragEnd={onDragEnd} onClick={() => onOpen(item)}>
    <div className="rcd-content-art"><Glyph kind={item.kind} /><span>{KINDS[item.kind] || '内容'}</span></div>
    <div className="rcd-content-body">
      <h3>{item.draft?.title || item.title}</h3>
      <p>{item.body || item.draft?.body?.slice(0, 120) || (zh ? '还没有正文' : 'No body yet')}</p>
      <div className="rcd-content-meta"><span>{item.platform}</span>{item.scheduledAt && <span>{item.scheduledAt.slice(0, 10)}</span>}<span className={`rcd-mini-dot is-${item.status}`} /></div>
    </div>
    {onMove && <div className="rcd-card-move">
      {STATUS_ORDER.filter(s => s !== item.status).slice(0, 2).map(s => <button type="button" key={s} onClick={e => { e.stopPropagation(); onMove(item, s) }}>{STATUS[s]}</button>)}
    </div>}
  </article>
}

export function ScheduleChip({ item, zh, onOpen }) {
  return <button type="button" className={`rcd-schedule-chip is-${item.status}`} onClick={() => onOpen(item)}>
    <span className="rcd-chip-dot" />
    <span className="rcd-chip-text"><strong>{item.draft?.title || item.title}</strong><small>{item.platform}</small></span>
    <span className="rcd-chip-status">{STATUS[item.status]}</span>
  </button>
}

export function MetricStat({ label, value, note, tone: color }) {
  return <div className={`rcd-stat tone-${color || 0}`}>
    <span>{label}</span>
    <strong>{typeof value === 'number' ? value.toLocaleString() : String(value ?? '0')}</strong>
    {note && <small>{note}</small>}
  </div>
}

export function PlatformBar({ name, value, max, zh }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0
  return <div className="rcd-platform">
    <div className="rcd-platform-head"><span>{name}</span><strong>{Number(value || 0).toLocaleString()}</strong></div>
    <div className="rcd-bar"><i style={{ width: `${pct}%` }} /></div>
  </div>
}

export function StyleCard({ style, active, zh, onUse }) {
  return <article className={`rcd-style-card ${active ? 'is-active' : ''}`}>
    <div className="rcd-style-art"><span>{style.name?.slice(0, 1) || '风'}</span><i /></div>
    <div className="rcd-style-body">
      <div className="rcd-style-title"><h3>{style.name}</h3>{active ? <span className="rcd-pill">{zh ? '当前' : 'Current'}</span> : <button type="button" className="rcd-link" onClick={onUse}>{zh ? '使用' : 'Use'}</button>}</div>
      <p>{style.tone || (zh ? '还没有语气描述' : 'No tone yet')}</p>
      {style.audience && <small>{zh ? '受众' : 'Audience'}：{style.audience}</small>}
      {style.rules && <div className="rcd-style-rule">{style.rules}</div>}
    </div>
  </article>
}

export function ProgressRail({ status, zh }) {
  const index = Math.max(0, STATUS_ORDER.indexOf(status || 'idea'))
  return <div className="rcd-progress-rail" aria-label={zh ? '内容进度' : 'Content progress'}>
    {STATUS_ORDER.map((stage, i) => <div key={stage} className={`rcd-progress-node ${i <= index ? 'is-done' : ''} ${i === index ? 'is-now' : ''}`}>
      <i>{i < index ? '✓' : i + 1}</i><span>{STATUS[stage]}</span>
    </div>)}
  </div>
}

export function DraftCard({ draft, zh, onCopy }) {
  if (!draft?.body) return <div className="rcd-draft-card is-empty"><span className="rcd-dash" /><p>{zh ? '还没有初稿。让主对话写一版，或直接在下方写。' : 'No draft yet. Ask the main chat, or write below.'}</p></div>
  return <article className="rcd-draft-card">
    <header><span className="rcd-kicker">DRAFT</span><span className="rcd-pill">{draft.model || 'dsalpha'}</span></header>
    <div className="rcd-draft-preview">{draft.body.slice(0, 420)}</div>
    <footer><span>{draft.body.length} {zh ? '字' : 'chars'}</span><button type="button" className="rcd-link" onClick={onCopy}>{zh ? '复制正文' : 'Copy'}</button></footer>
  </article>
}

export function useKindCounts(items) {
  return useMemo(() => {
    const counts = {}
    for (const item of items) counts[item.kind || 'note'] = (counts[item.kind || 'note'] || 0) + 1
    return counts
  }, [items])
}
