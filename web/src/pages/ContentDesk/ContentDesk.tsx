// @ts-nocheck
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { resolveChatWorkspace } from '@/hooks/useHomeWorkspace'
import {
  ContentCard, DraftCard, IdeaCard, KIND_GLYPH, KINDS, MetricStat, PlatformBar,
  ProgressRail, ScheduleChip, STATUS, STATUS_ORDER, StyleCard,
} from './cards'
import './ContentDesk.css'

const EMPTY = { title: '', body: '', url: '', kind: 'note', status: 'idea', platform: '小红书', tags: '', scheduledAt: '', draft: null }

function Icon({ name, size = 18 }) {
  const p = {
    spark: <><path d="M12 3l1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z"/></>,
    plus: <><path d="M12 5v14M5 12h14"/></>,
    chat: <><path d="M21 12a8 8 0 0 1-8 8H6l-3 2 1-5a8 8 0 1 1 17-5Z"/><path d="M8 10h8M8 14h5"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/></>,
    chart: <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></>,
    palette: <><path d="M12 3a9 9 0 1 0 0 18c1.4 0 2-.8 2-1.7 0-1.3-1.2-1.8-1.2-3 0-1 .8-1.8 2-1.8h1.7A4.5 4.5 0 0 0 21 10c0-3.9-4-7-9-7Z"/><circle cx="7.5" cy="11" r=".8" fill="currentColor"/><circle cx="10" cy="7.5" r=".8" fill="currentColor"/><circle cx="14.5" cy="7.8" r=".8" fill="currentColor"/></>,
    edit: <><path d="M4 20h4l10.5-10.5a2.8 2.8 0 0 0-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/></>,
    trash: <><path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3"/></>,
    close: <><path d="m6 6 12 12M18 6 6 18"/></>,
    external: <><path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></>,
    chevL: <><path d="m15 5-7 7 7 7"/></>, chevR: <><path d="m9 5 7 7-7 7"/></>,
  }[name] || null
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{p}</svg>
}

function Btn({ children, primary, quiet, ...props }) {
  return <button type="button" className={`rcd-btn${primary ? ' is-primary' : ''}${quiet ? ' is-quiet' : ''}`} {...props}>{children}</button>
}

export default function ContentDesk() {
  const { i18n } = useTranslation()
  const zh = i18n.language.startsWith('zh')
  const [data, setData] = useState(null)
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('ideas')
  const [editing, setEditing] = useState(null)
  const [toast, setToast] = useState(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const flash = useCallback((text) => {
    setToast({ text, key: Date.now() })
    window.setTimeout(() => setToast(null), 3000)
  }, [])
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const { data: next } = await api.get('/api/v1/content-desk/state')
      setData(next.state); setRevision(next.revision)
    } catch (e) { setError(e?.message || '加载失败') } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function applyOps(ops, label) {
    if (!ops?.length) return null
    setBusy(true)
    try {
      const { data: next } = await api.post('/api/v1/content-desk/ops', { base_revision: revision, ops })
      setData(next.state); setRevision(next.revision)
      if (label) flash(label)
      return next
    } catch (e) {
      if (e?.status === 409) { flash(zh ? '其他页面已更新，已刷新' : 'Updated elsewhere; reloading'); await load() }
      else flash(e?.message || '保存失败')
      return null
    } finally { setBusy(false) }
  }

  async function askAI(prompt) {
    if (!prompt.trim() || busy) return
    setBusy(true)
    try {
      const workspaceId = await resolveChatWorkspace(queryClient, 'all')
      navigate('/chat/t/__default__', { state: { workspaceId, draftMessage: prompt } })
    } catch {
      flash(zh ? '无法打开主对话，请稍后再试' : 'Could not open the main chat')
    } finally { setBusy(false) }
  }

  const moveItem = (item, status) => applyOps([{ op: 'update_item', id: item.id, status }], zh ? `已移到「${STATUS[status]}」` : `Moved to ${STATUS[status]}`)
  const nav = useMemo(() => [
    ['ideas', zh ? '灵感' : 'Ideas', 'spark'], ['content', zh ? '内容' : 'Content', 'edit'],
    ['schedule', zh ? '排期' : 'Schedule', 'calendar'], ['insights', zh ? '复盘' : 'Review', 'chart'],
    ['style', zh ? '风格' : 'Voice', 'palette'],
  ], [zh])

  if (loading) return <div className="rcd-root"><div className="rcd-loading">正在加载工作台…</div></div>
  if (error || !data) return <div className="rcd-root"><div className="rcd-error"><h2>{zh ? '工作台加载失败' : 'Failed to load'}</h2><p>{error}</p><Btn onClick={load}>{zh ? '重试' : 'Retry'}</Btn></div></div>

  return <div className="rcd-root">
    <div className="rcd-page">
      <div className="rcd-page-head">
        <div><p className="rcd-kicker">ROOST CONTENT DESK</p><h1>{zh ? '内容工作台' : 'Content Desk'}</h1><p className="rcd-lead">{zh ? '灵感 → 初稿 → 排期 → 复盘。数据和风格保存在你的账号里。' : 'Ideas → drafts → schedule → review. Saved to your account.'}</p></div>
        <div className="rcd-actions">
          <Btn quiet onClick={() => askAI(zh ? '帮我看看我的内容工作台，挑一个选题写成小红书初稿。' : 'Look at my Content Desk and turn one topic into a Xiaohongshu draft.')} disabled={busy}><Icon name="chat" size={15} />{zh ? '问 AI' : 'Ask AI'}</Btn>
          <Btn primary onClick={() => setEditing({ ...EMPTY })}><Icon name="plus" size={15} />{zh ? '新建' : 'New'}</Btn>
        </div>
      </div>
      <div className="rcd-top" style={{ position: 'static', borderBottom: '1px solid var(--rcd-line)', borderRadius: 12, marginBottom: 20, padding: 5, display: 'inline-flex' }}>
        {nav.map(([id, label, icon]) => <button type="button" key={id} className={tab === id ? 'is-on' : ''} onClick={() => setTab(id)}><Icon name={icon} size={15} />{label}</button>)}
      </div>
      {tab === 'ideas' && <Ideas state={data} zh={zh} onOpen={setEditing} onNew={() => setEditing({ ...EMPTY })} onMove={moveItem} onQuick={text => {
        const title = text.split(/[。！？\n]/)[0].slice(0, 60) || text.slice(0, 60)
        void applyOps([{ op: 'add_item', title, body: text, kind: 'note' }], zh ? '已记下' : 'Saved')
      }} />}
      {tab === 'content' && <Content state={data} zh={zh} onOpen={setEditing} onNew={() => setEditing({ ...EMPTY })} onMove={moveItem} />}
      {tab === 'schedule' && <Schedule state={data} zh={zh} onOpen={setEditing} />}
      {tab === 'insights' && <Insights state={data} zh={zh} onOpen={setEditing} onAdd={metric => applyOps([{ op: 'add_metric', ...metric }], zh ? '数据已记录' : 'Saved')} />}
      {tab === 'style' && <Voice state={data} zh={zh} onAdd={style => applyOps([{ op: 'add_style', ...style }], zh ? '风格已添加' : 'Style added')} onActive={id => applyOps([{ op: 'set_active_style', id }], zh ? '已切换风格' : 'Voice selected')} />}
    </div>
    {editing && <Editor item={editing} state={data} zh={zh} onClose={() => setEditing(null)} applyOps={applyOps} flash={flash} busy={busy} onAskAI={askAI} />}
    {toast && <div className="rcd-toast" key={toast.key}>{toast.text}</div>}
    <a className="rcd-console" href="https://www.roostbots.com/console/" target="_blank" rel="noreferrer" style={{ position: 'fixed', right: 20, bottom: 18 }}>Roost Console<Icon name="external" size={13} /></a>
  </div>
}

function Ideas({ state, zh, onOpen, onNew, onQuick, onMove }) {
  const [text, setText] = useState('')
  const items = state.items.filter(i => i.status === 'idea' || !i.status)
  return <>
    <div className="rcd-toolbar">
      <form className="rcd-quick" onSubmit={e => { e.preventDefault(); if (!text.trim()) return; onQuick(text.trim()); setText('') }}>
        <Icon name="spark" size={18} /><input value={text} onChange={e => setText(e.target.value)} placeholder={zh ? '记一句灵感，回车放进工作台' : 'Capture an idea, press Enter'} /><Btn primary type="submit" disabled={!text.trim()}>{zh ? '记下' : 'Save'}</Btn>
      </form>
      <div className="rcd-kind-counts">{Object.entries(KINDS).map(([kind, label]) => <span key={kind}><b>{KIND_GLYPH[kind]}</b>{label} {state.items.filter(i => (i.kind || 'note') === kind).length}</span>)}</div>
    </div>
    {items.length ? <div className="rcd-idea-grid">{items.map(item => <IdeaCard key={item.id} item={item} zh={zh} onOpen={onOpen} onMove={onMove} />)}</div> : <Empty zh={zh} title={zh ? '灵感墙还是空的' : 'No ideas yet'} body={zh ? '记一句想法，或者直接新建一条内容。' : 'Capture a thought or create a draft.'} action={<Btn primary onClick={onNew}>{zh ? '新建内容' : 'New content'}</Btn>} />}
  </>
}

function Content({ state, zh, onOpen, onNew, onMove }) {
  const [dragging, setDragging] = useState(null)
  const [over, setOver] = useState(null)
  const columns = STATUS_ORDER.map(status => ({ status, rows: state.items.filter(i => i.status === status) }))
  return <>
    <div className="rcd-section-head"><div><p className="rcd-kicker">PIPELINE</p><h2>{zh ? '内容看板' : 'Content board'}</h2></div><Btn primary onClick={onNew}><Icon name="plus" size={15} />{zh ? '新建' : 'New'}</Btn></div>
    <div className="rcd-board">
      {columns.map(({ status, rows }) => <section key={status} className={`rcd-board-col ${over === status ? 'is-over' : ''}`} onDragOver={e => { e.preventDefault(); setOver(status) }} onDragLeave={() => setOver(null)} onDrop={e => { e.preventDefault(); setOver(null); const id = e.dataTransfer.getData('text/content-desk-item'); const item = state.items.find(i => i.id === id); if (item) onMove(item, status) }}>
          <header><span className={`rcd-stage-dot is-${status}`} /><h3>{STATUS[status]}</h3><span>{rows.length}</span></header>
          <div className="rcd-board-list">
            {rows.map(item => <ContentCard key={item.id} item={item} zh={zh} onOpen={onOpen} onMove={onMove} dragging={dragging === item.id} onDragStart={e => { setDragging(item.id); e.dataTransfer.setData('text/content-desk-item', item.id); e.dataTransfer.effectAllowed = 'move' }} onDragEnd={() => setDragging(null)} />)}
            {!rows.length && <div className="rcd-col-empty">{zh ? '拖到这里' : 'Drop here'}</div>}
          </div>
        </section>)}
    </div>
  </>
}

function dayKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function Schedule({ state, zh, onOpen }) {
  const [cursor, setCursor] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1))
  const byDay = useMemo(() => {
    const map = {}
    for (const item of state.items) {
      if (!item.scheduledAt) continue
      const key = item.scheduledAt.slice(0, 10)
      ;(map[key] ||= []).push(item)
    }
    return map
  }, [state.items])
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const start = new Date(first); start.setDate(1 - first.getDay())
  const cells = Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d })
  const today = dayKey(new Date())
  const monthItems = Object.entries(byDay).filter(([key]) => key.startsWith(dayKey(cursor).slice(0, 7))).reduce((n, [, rows]) => n + rows.length, 0)
  const monthLabel = cursor.toLocaleDateString(zh ? 'zh-CN' : 'en-US', { year: 'numeric', month: 'long' })
  return <>
    <div className="rcd-section-head"><div><p className="rcd-kicker">PLAN</p><h2>{zh ? '排期日历' : 'Schedule'}</h2></div><span className="rcd-muted">{monthItems} {zh ? '条已排期' : 'scheduled'}</span></div>
    <div className="rcd-calendar">
      <header className="rcd-cal-head"><button type="button" className="rcd-icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))} aria-label="上个月"><Icon name="chevL" /></button><strong>{monthLabel}</strong><button type="button" className="rcd-icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))} aria-label="下个月"><Icon name="chevR" /></button><span className="rcd-grow" /><Btn quiet onClick={() => setCursor(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>{zh ? '今天' : 'Today'}</Btn></header>
      <div className="rcd-cal-week">{['日', '一', '二', '三', '四', '五', '六'].map(d => <span key={d}>{zh ? d : ['S', 'M', 'T', 'W', 'T', 'F', 'S'][['日', '一', '二', '三', '四', '五', '六'].indexOf(d)]}</span>)}</div>
      <div className="rcd-cal-grid">{cells.map(date => {
        const key = dayKey(date)
        const rows = byDay[key] || []
        return <div key={key} className={`rcd-cal-day ${date.getMonth() !== cursor.getMonth() ? 'is-out' : ''} ${key === today ? 'is-today' : ''}`}>
          <span className="rcd-cal-num">{date.getDate()}</span>
          <div className="rcd-cal-items">{rows.slice(0, 3).map(item => <ScheduleChip key={item.id} item={item} zh={zh} onOpen={onOpen} />)}{rows.length > 3 && <span className="rcd-cal-more">+{rows.length - 3}</span>}</div>
        </div>
      })}</div>
    </div>
  </>
}

function Insights({ state, zh, onOpen, onAdd }) {
  const totals = state.metrics.reduce((a, m) => ({ views: a.views + (m.views || 0), likes: a.likes + (m.likes || 0), comments: a.comments + (m.comments || 0), saves: a.saves + (m.saves || 0) }), { views: 0, likes: 0, comments: 0, saves: 0 })
  const platforms = Object.values(state.metrics.reduce((acc, m) => { const p = (acc[m.platform] ||= { name: m.platform, views: 0 }); p.views += m.views || 0; return acc }, {}))
  const maxPlatform = Math.max(1, ...platforms.map(p => p.views))
  const published = state.items.filter(i => i.status === 'published')
  const [form, setForm] = useState({ platform: '小红书', date: new Date().toISOString().slice(0, 10), views: '', likes: '', comments: '', saves: '' })
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))
  const engagement = totals.views ? ((totals.likes + totals.comments + totals.saves) / totals.views * 100).toFixed(1) : '0.0'
  return <>
    <div className="rcd-section-head"><div><p className="rcd-kicker">LEARN</p><h2>{zh ? '复盘' : 'Review'}</h2></div><span className="rcd-muted">{published.length} {zh ? '条已发布' : 'published'}</span></div>
    <div className="rcd-stat-grid">
      <MetricStat label={zh ? '播放 / 阅读' : 'Views'} value={totals.views} tone={0} />
      <MetricStat label={zh ? '点赞' : 'Likes'} value={totals.likes} tone={1} />
      <MetricStat label={zh ? '评论' : 'Comments'} value={totals.comments} tone={2} />
      <MetricStat label={zh ? '收藏' : 'Saves'} value={totals.saves} tone={3} />
      <MetricStat label={zh ? '互动率' : 'Engagement'} value={`${engagement}%`} tone={4} note={zh ? '赞评藏 / 播放' : 'Engaged / views'} />
    </div>
    <div className="rcd-insight-grid">
      <section className="rcd-panel"><header><span className="rcd-kicker">DISTRIBUTION</span><h3>{zh ? '平台分布' : 'By platform'}</h3></header>{platforms.length ? platforms.sort((a, b) => b.views - a.views).map(p => <PlatformBar key={p.name} name={p.name} value={p.views} max={maxPlatform} zh={zh} />) : <p className="rcd-muted">{zh ? '录入数据后显示。' : 'Add metrics to see this.'}</p>}</section>
      <section className="rcd-panel"><header><span className="rcd-kicker">TOP</span><h3>{zh ? '表现最好的内容' : 'Top content'}</h3></header>{published.length ? <div className="rcd-top-list">{published.slice(0, 3).map(item => <ContentCard key={item.id} item={item} zh={zh} onOpen={onOpen} />)}</div> : <p className="rcd-muted">{zh ? '发布内容后显示。' : 'Publish something first.'}</p>}</section>
    </div>
    <form className="rcd-metric-form" onSubmit={async e => { e.preventDefault(); await onAdd({ ...form, views: Number(form.views) || 0, likes: Number(form.likes) || 0, comments: Number(form.comments) || 0, saves: Number(form.saves) || 0 }); setForm(p => ({ ...p, views: '', likes: '', comments: '', saves: '' })) }}>
      <label className="rcd-field"><span>{zh ? '平台' : 'Platform'}</span><input value={form.platform} onChange={e => set('platform', e.target.value)} /></label>
      <label className="rcd-field"><span>{zh ? '日期' : 'Date'}</span><input type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label>
      {['views', 'likes', 'comments', 'saves'].map(k => <label className="rcd-field" key={k}><span>{{ views: '播放', likes: '赞', comments: '评', saves: '藏' }[k]}</span><input type="number" min="0" value={form[k]} onChange={e => set(k, e.target.value)} /></label>)}
      <Btn primary type="submit">{zh ? '记录' : 'Save'}</Btn>
    </form>
  </>
}

function Voice({ state, zh, onAdd, onActive }) {
  const [form, setForm] = useState({ name: '', tone: '', audience: '', rules: '' })
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))
  return <>
    <div className="rcd-section-head"><div><p className="rcd-kicker">VOICE</p><h2>{zh ? '写作风格' : 'Voice'}</h2></div><span className="rcd-muted">{state.styles.length} {zh ? '套风格' : 'styles'}</span></div>
    <div className="rcd-style-grid">{state.styles.map(s => <StyleCard key={s.id} style={s} active={s.id === state.activeStyleId} zh={zh} onUse={() => onActive(s.id)} />)}</div>
    <form className="rcd-style-form" onSubmit={async e => { e.preventDefault(); if (!form.name.trim()) return; await onAdd(form); setForm({ name: '', tone: '', audience: '', rules: '' }) }}>
      <div className="rcd-form-head"><span className="rcd-kicker">NEW VOICE</span><h3>{zh ? '添加一套风格' : 'Add a style'}</h3></div>
      <div className="rcd-grid-2"><label className="rcd-field"><span>{zh ? '名称' : 'Name'}</span><input required value={form.name} onChange={e => set('name', e.target.value)} placeholder={zh ? '我的口播风格' : 'My voice'} /></label><label className="rcd-field"><span>{zh ? '受众' : 'Audience'}</span><input value={form.audience} onChange={e => set('audience', e.target.value)} /></label></div>
      <label className="rcd-field"><span>{zh ? '语气' : 'Tone'}</span><input value={form.tone} onChange={e => set('tone', e.target.value)} /></label>
      <label className="rcd-field"><span>{zh ? '规则' : 'Rules'}</span><textarea rows={3} value={form.rules} onChange={e => set('rules', e.target.value)} placeholder={zh ? '先说结论；每段只讲一件事。' : 'Conclusion first; one point per paragraph.'} /></label>
      <Btn primary type="submit">{zh ? '添加风格' : 'Add style'}</Btn>
    </form>
  </>
}

function Editor({ item, state, zh, onClose, applyOps, flash, busy, onAskAI }) {
  const [form, setForm] = useState(() => ({ ...EMPTY, ...item, tags: Array.isArray(item.tags) ? item.tags.join(', ') : '', scheduledAt: item.scheduledAt ? item.scheduledAt.slice(0, 10) : '' }))
  const [saving, setSaving] = useState(false)
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))
  useEffect(() => { const h = e => { if (e.key === 'Escape') onClose() }; window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h) }, [onClose])
  const save = async () => {
    if (!form.title.trim()) return
    setSaving(true)
    const payload = { title: form.title, body: form.body, url: form.url || null, kind: form.kind, status: form.status, platform: form.platform, tags: form.tags.split(',').map(t => t.trim()).filter(Boolean), scheduledAt: form.scheduledAt || null, ...(form.draft ? { draft: form.draft } : {}) }
    const result = form.id ? await applyOps([{ op: 'update_item', id: form.id, ...payload }], zh ? '已保存' : 'Saved') : await applyOps([{ op: 'add_item', ...payload }], zh ? '已保存' : 'Saved')
    setSaving(false)
    if (result) onClose()
  }
  const remove = async () => { if (!form.id || !window.confirm('删除这条内容？')) return; const result = await applyOps([{ op: 'delete_item', id: form.id }], zh ? '已删除' : 'Deleted'); if (result) onClose() }
  const makeDraft = async () => {
    const prompt = zh
      ? `请把下面这条内容写成一篇小红书初稿，风格按我的内容工作台风格来（${state.styles.find(s => s.id === state.activeStyleId)?.name || '默认'}）：\n标题：${form.title}\n原始灵感：${form.body || '（无）'}\n${form.tags ? `标签：${form.tags}\n` : ''}请写在主对话里，我复制回工作台。`
      : `Write a Xiaohongshu draft from this Content Desk item in my current voice (${state.styles.find(s => s.id === state.activeStyleId)?.name || 'default'}):\nTitle: ${form.title}\nNotes: ${form.body || '(none)'}\nReturn it in the main chat.`
    await onAskAI(prompt)
  }
  return <div className="rcd-overlay" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
    <section className="rcd-editor" role="dialog" aria-modal="true" aria-label={zh ? '编辑内容' : 'Edit content'}>
      <header className="rcd-editor-head"><div><span className="rcd-kicker">{STATUS[form.status] || 'CONTENT'}</span><h2>{zh ? '编辑内容' : 'Edit content'}</h2></div><button type="button" className="rcd-icon-btn" onClick={onClose} aria-label="关闭"><Icon name="close" /></button></header>
      <div className="rcd-editor-body">
        <ProgressRail status={form.status} zh={zh} />
        <div className="rcd-grid-2"><label className="rcd-field"><span>{zh ? '标题' : 'Title'}</span><input value={form.title} onChange={e => set('title', e.target.value)} autoFocus /></label><label className="rcd-field"><span>{zh ? '类型' : 'Kind'}</span><select value={form.kind} onChange={e => set('kind', e.target.value)}>{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>
        <div className="rcd-grid-3"><label className="rcd-field"><span>{zh ? '状态' : 'Status'}</span><select value={form.status} onChange={e => set('status', e.target.value)}>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="rcd-field"><span>{zh ? '平台' : 'Platform'}</span><input value={form.platform} onChange={e => set('platform', e.target.value)} /></label><label className="rcd-field"><span>{zh ? '排期' : 'Date'}</span><input type="date" value={form.scheduledAt} onChange={e => set('scheduledAt', e.target.value)} /></label></div>
        {(form.kind === 'link' || form.kind === 'clip' || form.url) && <label className="rcd-field"><span>{zh ? '链接' : 'URL'}</span><input value={form.url || ''} onChange={e => set('url', e.target.value)} placeholder="https://" /></label>}
        <label className="rcd-field"><span>{zh ? '灵感 / 备注' : 'Idea / notes'}</span><textarea rows={4} value={form.body} onChange={e => set('body', e.target.value)} /></label>
        <label className="rcd-field"><span>{zh ? '标签' : 'Tags'}</span><input value={form.tags} onChange={e => set('tags', e.target.value)} placeholder={zh ? '逗号分隔' : 'comma separated'} /></label>
        <div className="rcd-draft-head"><div><span className="rcd-kicker">DRAFT</span><h3>{zh ? '初稿' : 'Draft'}</h3></div><div className="rcd-actions"><Btn onClick={makeDraft} disabled={saving || busy || !form.title.trim()}><Icon name="spark" size={15} />{saving ? '处理中…' : (zh ? '让 AI 写' : 'Ask AI')}</Btn>{form.draft?.body && <Btn quiet onClick={() => navigator.clipboard?.writeText(form.draft.body).then(() => flash('正文已复制'))}><Icon name="download" size={15} />复制正文</Btn>}</div></div>
        {form.draft?.body ? <div className="rcd-draft"><textarea rows={14} value={form.draft.body} onChange={e => set('draft', { ...form.draft, body: e.target.value })} /><p className="rcd-muted">{zh ? '生成模型' : 'Model'}：{form.draft.model || 'dsalpha'} · {zh ? '风格' : 'Voice'}：{state.styles.find(s => s.id === state.activeStyleId)?.name || '—'}</p></div> : <DraftCard zh={zh} draft={null} />}
      </div>
      <footer className="rcd-editor-foot">{form.id && <Btn quiet onClick={remove}><Icon name="trash" size={15} />{zh ? '删除' : 'Delete'}</Btn>}<span className="rcd-grow" /><Btn quiet onClick={onClose}>{zh ? '取消' : 'Cancel'}</Btn><Btn primary onClick={save} disabled={saving || !form.title.trim()}>{zh ? '保存' : 'Save'}</Btn></footer>
    </section>
  </div>
}

function Empty({ zh, title, body, action }) {
  return <div className="rcd-empty-state"><div className="rcd-empty-icon"><Icon name="spark" size={24} /></div><h3>{title}</h3><p>{body}</p>{action}</div>
}
