// @ts-nocheck
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { resolveChatWorkspace } from '@/hooks/useHomeWorkspace'
import './ContentDesk.css'

const STATUS = { idea: '灵感', draft: '初稿', ready: '待发布', published: '已发布' }
const KINDS = { note: '笔记', link: '链接', quote: '金句', topic: '选题', clip: '素材' }
const EMPTY = { title: '', body: '', kind: 'note', status: 'idea', platform: '小红书', tags: '', scheduledAt: '', draft: null }

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
    close: <><path d="m6 6 12 12M18 6 6 18"/></>, download: <><path d="M12 3v12M7 10l5 5 5-5M4 21h16"/></>,
    external: <><path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></>,
    send: <><path d="m22 2-7 20-4-9-9-4 20-7Z"/><path d="M22 2 11 13"/></>,
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

  const nav = useMemo(() => [
    ['ideas', zh ? '灵感' : 'Ideas', 'spark'], ['content', zh ? '内容' : 'Content', 'edit'],
    ['schedule', zh ? '排期' : 'Schedule', 'calendar'], ['insights', zh ? '复盘' : 'Review', 'chart'],
    ['style', zh ? '风格' : 'Voice', 'palette'],
  ], [zh])

  if (loading) return <div className="rcd-root"><div className="rcd-loading">正在加载工作台…</div></div>
  if (error || !data) return <div className="rcd-root"><div className="rcd-error"><h2>{zh ? '工作台加载失败' : 'Failed to load'}</h2><p>{error}</p><Btn onClick={load}>{zh ? '重试' : 'Retry'}</Btn></div></div>

  const activeStyle = data.styles.find(s => s.id === data.activeStyleId)

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
      {tab === 'ideas' && <Ideas state={data} zh={zh} onOpen={setEditing} onNew={() => setEditing({ ...EMPTY })} onQuick={text => {
        const title = text.split(/[。！？\n]/)[0].slice(0, 60) || text.slice(0, 60)
        void applyOps([{ op: 'add_item', title, body: text, kind: 'note' }], zh ? '已记下' : 'Saved')
      }} />}
      {tab === 'content' && <Content state={data} zh={zh} onOpen={setEditing} onNew={() => setEditing({ ...EMPTY })} />}
      {tab === 'schedule' && <Schedule state={data} zh={zh} onOpen={setEditing} />}
      {tab === 'insights' && <Insights state={data} zh={zh} onAdd={metric => applyOps([{ op: 'add_metric', ...metric }], zh ? '数据已记录' : 'Saved')} />}
      {tab === 'style' && <Voice state={data} zh={zh} onAdd={style => applyOps([{ op: 'add_style', ...style }], zh ? '风格已添加' : 'Style added')} onActive={id => applyOps([{ op: 'set_active_style', id }], zh ? '已切换风格' : 'Voice selected')} />}
    </div>
    {editing && <Editor item={editing} state={data} zh={zh} onClose={() => setEditing(null)} applyOps={applyOps} flash={flash} busy={busy} onAskAI={askAI} />}
    {toast && <div className="rcd-toast" key={toast.key}>{toast.text}</div>}
    <a className="rcd-console" href="https://www.roostbots.com/console/" target="_blank" rel="noreferrer" style={{ position: 'fixed', right: 20, bottom: 18 }}>Roost Console<Icon name="external" size={13} /></a>
  </div>
}

function Ideas({ state, zh, onOpen, onNew, onQuick }) {
  const [text, setText] = useState('')
  const items = state.items.filter(i => i.status === 'idea' || !i.status)
  return <>
    <form className="rcd-quick" onSubmit={e => { e.preventDefault(); if (!text.trim()) return; onQuick(text.trim()); setText('') }}>
      <Icon name="spark" size={18} /><input value={text} onChange={e => setText(e.target.value)} placeholder={zh ? '记一句灵感，回车放进工作台' : 'Capture an idea, press Enter'} /><Btn primary type="submit" disabled={!text.trim()}>{zh ? '记下' : 'Save'}</Btn>
    </form>
    {items.length ? <div className="rcd-cards">{items.map(item => <button type="button" className="rcd-card" key={item.id} onClick={() => onOpen(item)}><span className="rcd-card-kind">{KINDS[item.kind] || '灵感'}</span><h3>{item.title}</h3>{item.body && <p>{item.body.slice(0, 150)}</p>}<span className="rcd-card-foot">{item.tags?.length ? item.tags.map(t => `#${t}`).join(' ') : (zh ? '未分类' : 'Unsorted')}</span></button>)}</div> : <Empty zh={zh} title={zh ? '灵感墙还是空的' : 'No ideas yet'} body={zh ? '记一句想法，或者直接新建一条内容。' : 'Capture a thought or create a draft.'} action={<Btn primary onClick={onNew}>{zh ? '新建内容' : 'New content'}</Btn>} />}
  </>
}

function Content({ state, zh, onOpen, onNew }) {
  const rows = state.items.filter(i => i.status !== 'idea')
  return <>
    <div className="rcd-page-head" style={{ marginTop: 0 }}><h2>{zh ? '内容' : 'Content'}</h2><Btn primary onClick={onNew}><Icon name="plus" size={15} />{zh ? '新建' : 'New'}</Btn></div>
    {rows.length ? <div className="rcd-list">{rows.map(item => <button type="button" className="rcd-row" key={item.id} onClick={() => onOpen(item)}><span className="rcd-status">{STATUS[item.status] || item.status}</span><span className="rcd-row-main"><strong>{item.draft?.title || item.title}</strong><small>{item.body || item.draft?.body?.slice(0, 100) || '还没有正文'}</small></span><span className="rcd-row-meta">{item.platform}{item.scheduledAt ? ` · ${item.scheduledAt.slice(0, 10)}` : ''}</span><Icon name="edit" size={16} /></button>)}</div> : <Empty zh={zh} title={zh ? '还没有内容' : 'No content yet'} body={zh ? '把一条灵感变成初稿。' : 'Turn an idea into a draft.'} action={<Btn primary onClick={onNew}>{zh ? '新建内容' : 'New content'}</Btn>} />}
  </>
}

function Schedule({ state, zh, onOpen }) {
  const rows = [...state.items].filter(i => i.scheduledAt).sort((a, b) => a.scheduledAt.localeCompare(b.scheduledAt))
  return <><div className="rcd-page-head" style={{ marginTop: 0 }}><h2>{zh ? '排期' : 'Schedule'}</h2></div>{rows.length ? <div className="rcd-schedule">{rows.map(item => <button type="button" className="rcd-schedule-row" key={item.id} onClick={() => onOpen(item)}><time>{item.scheduledAt.slice(0, 10)}</time><span className="rcd-dot" /><span>{item.draft?.title || item.title}</span><small>{item.platform}</small></button>)}</div> : <Empty zh={zh} title={zh ? '还没有排期' : 'Nothing scheduled'} body={zh ? '在内容里设置日期。' : 'Set a date in a content item.'} />}</>}

function Insights({ state, zh, onAdd }) {
  const totals = state.metrics.reduce((a, m) => ({ views: a.views + (m.views || 0), likes: a.likes + (m.likes || 0), comments: a.comments + (m.comments || 0), saves: a.saves + (m.saves || 0) }), { views: 0, likes: 0, comments: 0, saves: 0 })
  const [form, setForm] = useState({ platform: '小红书', date: new Date().toISOString().slice(0, 10), views: '', likes: '', comments: '', saves: '' })
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))
  return <>
    <div className="rcd-page-head" style={{ marginTop: 0 }}><h2>{zh ? '复盘' : 'Review'}</h2></div>
    <div className="rcd-metrics">{[['播放', totals.views], ['点赞', totals.likes], ['评论', totals.comments], ['收藏', totals.saves]].map(([l, v]) => <div className="rcd-metric" key={l}><span>{l}</span><strong>{v.toLocaleString()}</strong></div>)}</div>
    <form className="rcd-metric-form" onSubmit={async e => { e.preventDefault(); await onAdd({ ...form, views: Number(form.views) || 0, likes: Number(form.likes) || 0, comments: Number(form.comments) || 0, saves: Number(form.saves) || 0 }); setForm(p => ({ ...p, views: '', likes: '', comments: '', saves: '' })) }}>
      <label className="rcd-field"><span>{zh ? '平台' : 'Platform'}</span><input value={form.platform} onChange={e => set('platform', e.target.value)} /></label>
      <label className="rcd-field"><span>{zh ? '日期' : 'Date'}</span><input type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label>
      {['views', 'likes', 'comments', 'saves'].map(k => <label className="rcd-field" key={k}><span>{{ views: '播放', likes: '赞', comments: '评', saves: '藏' }[k]}</span><input type="number" min="0" value={form[k]} onChange={e => set(k, e.target.value)} /></label>)}
      <Btn primary type="submit">{zh ? '记录' : 'Save'}</Btn>
    </form>
    {state.metrics.length ? <div className="rcd-list">{state.metrics.slice(0, 30).map(m => <div className="rcd-row" key={m.id}><span className="rcd-status">{m.platform}</span><span className="rcd-row-main"><strong>{m.date}</strong><small>{m.views} 播放 · {m.likes} 赞 · {m.saves} 收藏</small></span></div>)}</div> : <Empty zh={zh} title={zh ? '还没有数据' : 'No data yet'} body={zh ? '发布之后把数据录进来。' : 'Add performance after publishing.'} />}
  </>
}

function Voice({ state, zh, onAdd, onActive }) {
  const [form, setForm] = useState({ name: '', tone: '', audience: '', rules: '' })
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))
  return <>
    <div className="rcd-page-head" style={{ marginTop: 0 }}><h2>{zh ? '风格' : 'Voice'}</h2></div>
    <form className="rcd-style-form" onSubmit={async e => { e.preventDefault(); if (!form.name.trim()) return; await onAdd(form); setForm({ name: '', tone: '', audience: '', rules: '' }) }}>
      <div className="rcd-grid-2"><label className="rcd-field"><span>{zh ? '名称' : 'Name'}</span><input required value={form.name} onChange={e => set('name', e.target.value)} placeholder={zh ? '我的口播风格' : 'My voice'} /></label><label className="rcd-field"><span>{zh ? '受众' : 'Audience'}</span><input value={form.audience} onChange={e => set('audience', e.target.value)} /></label></div>
      <label className="rcd-field"><span>{zh ? '语气' : 'Tone'}</span><input value={form.tone} onChange={e => set('tone', e.target.value)} /></label>
      <label className="rcd-field"><span>{zh ? '规则' : 'Rules'}</span><textarea rows={3} value={form.rules} onChange={e => set('rules', e.target.value)} /></label>
      <Btn primary type="submit">{zh ? '添加风格' : 'Add style'}</Btn>
    </form>
    <div className="rcd-styles">{state.styles.map(s => <article className={`rcd-style${s.id === state.activeStyleId ? ' is-active' : ''}`} key={s.id}><div className="rcd-style-head"><h3>{s.name}</h3>{s.id === state.activeStyleId ? <span className="rcd-pill">{zh ? '当前' : 'Current'}</span> : <Btn quiet onClick={() => onActive(s.id)}>{zh ? '设为当前' : 'Use'}</Btn>}</div><p>{s.tone || '—'}</p>{s.audience && <small>{s.audience}</small>}{s.rules && <p className="rcd-rules">{s.rules}</p>}</article>)}</div>
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
    const payload = { title: form.title, body: form.body, kind: form.kind, status: form.status, platform: form.platform, tags: form.tags.split(',').map(t => t.trim()).filter(Boolean), scheduledAt: form.scheduledAt || null, ...(form.draft ? { draft: form.draft } : {}) }
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
        <div className="rcd-grid-2"><label className="rcd-field"><span>{zh ? '标题' : 'Title'}</span><input value={form.title} onChange={e => set('title', e.target.value)} autoFocus /></label><label className="rcd-field"><span>{zh ? '类型' : 'Kind'}</span><select value={form.kind} onChange={e => set('kind', e.target.value)}>{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>
        <div className="rcd-grid-3"><label className="rcd-field"><span>{zh ? '状态' : 'Status'}</span><select value={form.status} onChange={e => set('status', e.target.value)}>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="rcd-field"><span>{zh ? '平台' : 'Platform'}</span><input value={form.platform} onChange={e => set('platform', e.target.value)} /></label><label className="rcd-field"><span>{zh ? '排期' : 'Date'}</span><input type="date" value={form.scheduledAt} onChange={e => set('scheduledAt', e.target.value)} /></label></div>
        <label className="rcd-field"><span>{zh ? '灵感 / 备注' : 'Idea / notes'}</span><textarea rows={4} value={form.body} onChange={e => set('body', e.target.value)} /></label>
        <label className="rcd-field"><span>{zh ? '标签' : 'Tags'}</span><input value={form.tags} onChange={e => set('tags', e.target.value)} placeholder={zh ? '逗号分隔' : 'comma separated'} /></label>
        <div className="rcd-draft-head"><div><span className="rcd-kicker">DRAFT</span><h3>{zh ? '初稿' : 'Draft'}</h3></div><div className="rcd-actions"><Btn onClick={makeDraft} disabled={saving || busy || !form.title.trim()}><Icon name="spark" size={15} />{saving ? '处理中…' : (zh ? '让 AI 写' : 'Ask AI')}</Btn>{form.draft?.body && <Btn quiet onClick={() => navigator.clipboard?.writeText(form.draft.body).then(() => flash('正文已复制'))}><Icon name="download" size={15} />复制正文</Btn>}</div></div>
        {form.draft?.body ? <div className="rcd-draft"><textarea rows={14} value={form.draft.body} onChange={e => set('draft', { ...form.draft, body: e.target.value })} /><p className="rcd-muted">{zh ? '生成模型' : 'Model'}：{form.draft.model || 'LangAlpha'} · {zh ? '风格' : 'Voice'}：{state.styles.find(s => s.id === state.activeStyleId)?.name || '—'}</p></div> : <p className="rcd-empty">{zh ? '还没有初稿。可以让主对话帮你写，再复制回来；也可以直接写。' : 'No draft yet. Ask the main chat to write one, then paste it back, or write below.'}</p>}
      </div>
      <footer className="rcd-editor-foot">{form.id && <Btn quiet onClick={remove}><Icon name="trash" size={15} />{zh ? '删除' : 'Delete'}</Btn>}<span className="rcd-grow" /><Btn quiet onClick={onClose}>{zh ? '取消' : 'Cancel'}</Btn><Btn primary onClick={save} disabled={saving || !form.title.trim()}>{zh ? '保存' : 'Save'}</Btn></footer>
    </section>
  </div>
}

function Empty({ zh, title, body, action }) {
  return <div className="rcd-empty-state"><div className="rcd-empty-icon"><Icon name="spark" size={24} /></div><h3>{title}</h3><p>{body}</p>{action}</div>
}
