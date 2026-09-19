/**
 * The shared knowledge-base vault, surfaced on the dashboard.
 *
 * The vault is a directory of markdown notes that athena writes and reads
 * through its own tools; the agent has always been able to reach it and the
 * dashboard never could. This is that same content, read-only.
 *
 * Read-only is the design, not a limitation to lift later: notes are titled,
 * tagged and cross-linked by the agent as it writes them, and a plain textarea
 * here would produce notes its own retrieval ranks badly. So the widget is a
 * window — browse, search, read — and writing stays in the conversation.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BookOpen, Search, ChevronLeft, Folder } from 'lucide-react';

import { api } from '@/api/client';
import { registerWidget } from '../framework/WidgetRegistry';
import type { WidgetRenderProps } from '../types';

type KnowledgeConfig = { folder?: string | null; limit?: number };

type NoteRow = { path: string; title: string; updated?: string };
type SearchHit = {
  path: string;
  title: string;
  snippet: string;
  tags: string[];
  score: number;
};
type FolderRow = { name: string; count: number };
type Summary = { configured: boolean; count: number; folders: FolderRow[] };
type NoteDetail = {
  path: string;
  title: string;
  text: string;
  tags: string[];
  updated?: string;
};

function KnowledgeWidget({ instance, updateConfig }: WidgetRenderProps<KnowledgeConfig>) {
  const { t } = useTranslation();
  const folder = instance.config?.folder ?? null;
  const limit = instance.config?.limit ?? 60;

  const [summary, setSummary] = useState<Summary | null>(null);
  const [notes, setNotes] = useState<NoteRow[]>([]);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [query, setQuery] = useState('');
  const [detail, setDetail] = useState<NoteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  // A slower response must not overwrite a newer one's results.
  const requestSeq = useRef(0);

  const loadList = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(true);
    try {
      const [s, n] = await Promise.all([
        api.get<Summary>('/api/v1/knowledge/summary'),
        api.get<{ notes: NoteRow[] }>('/api/v1/knowledge/notes', {
          params: { folder: folder ?? undefined, limit },
        }),
      ]);
      if (seq !== requestSeq.current) return;
      setSummary(s.data);
      setNotes(n.data.notes ?? []);
    } catch {
      if (seq === requestSeq.current) {
        setSummary({ configured: false, count: 0, folders: [] });
        setNotes([]);
      }
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [folder, limit]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // Search is debounced: the vault has no index, so every keystroke would rank
  // the whole tree.
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits(null);
      return;
    }
    const seq = ++requestSeq.current;
    const timer = setTimeout(async () => {
      try {
        const res = await api.get<{ hits: SearchHit[] }>('/api/v1/knowledge/search', {
          params: { q, limit: 30, folder: folder ?? undefined },
        });
        if (seq === requestSeq.current) setHits(res.data.hits ?? []);
      } catch {
        if (seq === requestSeq.current) setHits([]);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query, folder]);

  const open = useCallback(async (path: string) => {
    setDetail({ path, title: '', text: t('dashboard.widgets.knowledge.loading'), tags: [] });
    try {
      const res = await api.get<NoteDetail>(
        `/api/v1/knowledge/notes/${path.split('/').map(encodeURIComponent).join('/')}`,
      );
      setDetail(res.data);
    } catch {
      setDetail(null);
    }
  }, [t]);

  const rows = useMemo(() => hits ?? notes, [hits, notes]);

  const chipStyle = (active: boolean): React.CSSProperties => ({
    padding: '2px 8px',
    borderRadius: 999,
    fontSize: 11,
    whiteSpace: 'nowrap',
    cursor: 'pointer',
    border: '1px solid var(--color-border-default)',
    background: active ? 'var(--color-accent-subtle, rgba(208,125,51,0.12))' : 'transparent',
    color: active ? 'var(--color-accent)' : 'var(--color-text-secondary)',
  });

  if (detail) {
    return (
      <div className="flex flex-col h-full min-h-0">
        <div className="flex items-center gap-2 px-3 py-2 flex-shrink-0">
          <button
            type="button"
            onClick={() => setDetail(null)}
            className="flex items-center gap-1 text-xs clips-focus-ring rounded px-1.5 py-0.5"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <ChevronLeft size={13} />
            {t('dashboard.widgets.knowledge.back')}
          </button>
          <span className="text-xs truncate" style={{ color: 'var(--color-text-tertiary)' }}>
            {detail.path}
          </span>
        </div>
        <h3 className="px-3 pb-2 text-sm font-medium flex-shrink-0">{detail.title}</h3>
        <div
          className="flex-1 min-h-0 overflow-auto px-3 pb-3 text-xs leading-relaxed whitespace-pre-wrap"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {detail.text}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header: count + folders */}
      <div className="flex items-center gap-2 px-3 pt-2.5 pb-1.5 flex-shrink-0">
        <BookOpen size={14} style={{ color: 'var(--color-accent)' }} />
        <span className="text-xs font-medium">
          {summary?.configured
            ? t('dashboard.widgets.knowledge.count', { count: summary.count })
            : t('dashboard.widgets.knowledge.unavailable')}
        </span>
      </div>
      {summary?.configured && summary.folders.length > 0 && (
        <div className="flex gap-1.5 px-3 pb-2 overflow-x-auto flex-shrink-0">
          <button
            type="button"
            style={chipStyle(!folder)}
            onClick={() => updateConfig({ folder: null })}
          >
            {t('dashboard.widgets.knowledge.all')}
          </button>
          {summary.folders.map((f) => (
            <button
              key={f.name}
              type="button"
              style={chipStyle(folder === f.name)}
              onClick={() => updateConfig({ folder: f.name === '(根目录)' ? null : f.name })}
            >
              {f.name} {f.count}
            </button>
          ))}
        </div>
      )}

      {/* Search */}
      <div className="px-3 pb-2 flex-shrink-0">
        <div
          className="flex items-center gap-1.5 px-2 py-1 rounded-md"
          style={{ border: '1px solid var(--color-border-default)' }}
        >
          <Search size={12} style={{ color: 'var(--color-text-tertiary)' }} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('dashboard.widgets.knowledge.searchPlaceholder')}
            className="flex-1 bg-transparent text-xs outline-none border-0"
          />
        </div>
      </div>

      {/* List */}
      <div className="flex-1 min-h-0 overflow-auto">
        {loading && !rows.length ? (
          <p className="px-3 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('dashboard.widgets.knowledge.loading')}
          </p>
        ) : !rows.length ? (
          <p className="px-3 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {hits
              ? t('dashboard.widgets.knowledge.noResults')
              : t('dashboard.widgets.knowledge.empty')}
          </p>
        ) : (
          rows.map((row) => (
            <button
              key={row.path}
              type="button"
              onClick={() => void open(row.path)}
              className="w-full text-left px-3 py-1.5 hover:bg-[var(--color-surface-hover)] clips-focus-ring block"
            >
              <div className="text-xs truncate">{row.title || row.path}</div>
              {'snippet' in row && row.snippet ? (
                <div
                  className="text-[11px] leading-snug line-clamp-2"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  {row.snippet}
                </div>
              ) : (
                <div
                  className="text-[11px] flex items-center gap-1"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  <Folder size={10} />
                  {row.path}
                </div>
              )}
            </button>
          ))
        )}
      </div>
    </div>
  );
}

registerWidget<KnowledgeConfig>({
  type: 'knowledge.base',
  titleKey: 'dashboard.widgets.knowledge.title',
  descriptionKey: 'dashboard.widgets.knowledge.description',
  category: 'intel',
  icon: BookOpen,
  component: KnowledgeWidget,
  defaultConfig: { folder: null, limit: 60 },
  defaultSize: { w: 6, h: 26 },
  minSize: { w: 3, h: 14 },
});

export default KnowledgeWidget;
