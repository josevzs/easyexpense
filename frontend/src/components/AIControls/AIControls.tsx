import { useState } from 'react';
import { runCategorizationStream, applyCategorizations, suggestCategories } from '../../api/client';
import { useAppStore } from '../../store/appStore';
import type { SSEProgressEvent } from '../../api/client';
import './AIControls.css';

const ALL_PRESETS = [
  'Estancias', 'Alquiler de coches', 'Comidas y cenas', 'Desayunos y cafés',
  'Entradas', 'Gasolina', 'Peajes', 'Trenes', 'Autobuses', 'Barcos y ferrys',
  'Aviones', 'Gastos personales', 'Supermercado', 'Farmacia', 'Parking',
  'Taxis', 'Transfer', 'Otros',
];

export default function AIControls() {
  const {
    sessionId, expenses, suggestions, allCategories,
    isLoadingAI, setLoadingAI, setSuggestions, applyAllSuggestions,
    addCustomCategory, setStep, setError,
  } = useAppStore();

  // Category management state
  const [activeCategories, setActiveCategories] = useState<string[]>(allCategories);
  const [customInput, setCustomInput] = useState('');
  const [suggestingCats, setSuggestingCats] = useState(false);

  // Progress state
  const [progress, setProgress] = useState<{ completed: number; total: number } | null>(null);
  const [progressMsg, setProgressMsg] = useState('');

  const uncategorized = expenses.filter(e => e.category === 'UNCATEGORIZED').length;
  const highConf = suggestions.filter(s => s.confidence >= 0.85).length;

  // ── Category management ──────────────────
  function toggleCategory(cat: string) {
    setActiveCategories(prev =>
      prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
    );
  }

  function addCustomCategory_() {
    const cat = customInput.trim();
    if (!cat || activeCategories.includes(cat)) return;
    setActiveCategories(prev => [...prev, cat]);
    addCustomCategory(cat);
    setCustomInput('');
  }

  async function handleSuggestCategories() {
    if (!sessionId) return;
    setSuggestingCats(true);
    try {
      const suggested = await suggestCategories(sessionId);
      setActiveCategories(suggested);
      for (const c of suggested) addCustomCategory(c);
    } catch {
      setError('Failed to suggest categories');
    } finally {
      setSuggestingCats(false);
    }
  }

  // ── AI run ───────────────────────────────
  async function handleRunAI() {
    if (!sessionId) return;
    setLoadingAI(true);
    setError(null);
    setProgress(null);
    setProgressMsg('Connecting…');

    const allSuggestions: typeof suggestions = [];
    const newCats: string[] = [];

    try {
      await runCategorizationStream(sessionId, (event: SSEProgressEvent) => {
        switch (event.type) {
          case 'start':
            setProgressMsg(`Processing ${event.total} expenses in ${event.chunks} batches…`);
            setProgress({ completed: 0, total: event.total });
            break;
          case 'progress':
            setProgress({ completed: event.completed, total: event.total });
            setProgressMsg(`Batch ${event.chunk}/${event.chunks} — ${event.completed}/${event.total} done`);
            break;
          case 'result':
            allSuggestions.push(...event.suggestions);
            newCats.push(...event.new_categories);
            break;
          case 'error':
            setError(event.message);
            break;
        }
      });
      setSuggestions(allSuggestions, newCats);
      setProgressMsg(`Done — ${allSuggestions.length} suggestions ready`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'AI categorization failed');
    } finally {
      setLoadingAI(false);
    }
  }

  async function handleApplyAll() {
    if (!sessionId) return;
    const applications = applyAllSuggestions(0.85);
    if (applications.length > 0) {
      await applyCategorizations(sessionId, applications).catch(() => {});
    }
  }

  const pct = progress ? Math.round((progress.completed / progress.total) * 100) : 0;

  return (
    <div className="ai-controls">

      {/* ── Categories panel ── */}
      <section className="ai-section">
        <div className="section-header">
          <span className="section-title">CATEGORIES</span>
          <div className="section-actions">
            <button
              className="btn btn-sm"
              onClick={handleSuggestCategories}
              disabled={suggestingCats || !sessionId}
              title="Let AI suggest which categories fit this trip"
            >
              {suggestingCats ? <span className="spinner" /> : '✦'}
              {suggestingCats ? 'Suggesting…' : 'Auto-suggest for this trip'}
            </button>
            <button className="btn btn-sm" onClick={() => setActiveCategories(ALL_PRESETS)}>
              Reset
            </button>
          </div>
        </div>

        <div className="cat-grid">
          {[...new Set([...ALL_PRESETS, ...allCategories])].map(cat => {
            const on = activeCategories.includes(cat);
            const isCustom = !ALL_PRESETS.includes(cat);
            return (
              <button
                key={cat}
                className={`cat-chip ${on ? 'active' : ''} ${isCustom ? 'custom' : ''}`}
                onClick={() => toggleCategory(cat)}
              >
                {cat}
              </button>
            );
          })}
        </div>

        <div className="cat-add-row">
          <input
            type="text"
            placeholder="Add custom category…"
            value={customInput}
            onChange={e => setCustomInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addCustomCategory_()}
          />
          <button className="btn btn-sm" onClick={addCustomCategory_} disabled={!customInput.trim()}>
            Add
          </button>
        </div>
        <p className="cat-hint">
          {activeCategories.length} categories active — click to toggle. AI will only assign from these.
        </p>
      </section>

      {/* ── Stats ── */}
      <section className="ai-section ai-stats-row">
        <div className="stat-cell">
          <span className="stat-n">{expenses.length}</span>
          <span className="stat-l">Total</span>
        </div>
        <div className="stat-cell">
          <span className="stat-n">{uncategorized}</span>
          <span className="stat-l">Uncategorized</span>
        </div>
        {suggestions.length > 0 && (
          <div className="stat-cell">
            <span className="stat-n">{suggestions.length}</span>
            <span className="stat-l">AI Suggestions</span>
          </div>
        )}
        {suggestions.length > 0 && (
          <div className="stat-cell">
            <span className="stat-n">{highConf}</span>
            <span className="stat-l">High confidence</span>
          </div>
        )}
      </section>

      {/* ── Progress bar ── */}
      {(isLoadingAI || progress) && (
        <section className="ai-section ai-progress">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: isLoadingAI ? `${pct}%` : '100%' }} />
          </div>
          <div className="progress-label">
            <span className="mono">{progressMsg}</span>
            {progress && <span className="mono">{pct}%</span>}
          </div>
        </section>
      )}

      {/* ── Actions ── */}
      <section className="ai-section ai-actions-row">
        <button className="btn btn-fill" onClick={handleRunAI} disabled={isLoadingAI || !sessionId}>
          {isLoadingAI ? <span className="spinner spinner-white" /> : '→'}
          {isLoadingAI ? 'Running AI…' : 'Run AI Categorization'}
        </button>

        {suggestions.length > 0 && (
          <button className="btn" onClick={handleApplyAll} disabled={highConf === 0}>
            Apply {highConf} high-confidence (≥85%)
          </button>
        )}

        <button className="btn" onClick={() => setStep('review')}>
          Review & Edit →
        </button>
      </section>

      {/* ── New category proposals ── */}
      {useAppStore(s => s.newCategoriesProposed).length > 0 && (
        <section className="ai-section ai-new-cats">
          <span className="section-title">AI PROPOSED NEW CATEGORIES</span>
          <div className="new-cats-list">
            {useAppStore(s => s.newCategoriesProposed).map(cat => (
              <span key={cat} className="new-cat-tag">
                {cat}
                <button onClick={() => { addCustomCategory(cat); setActiveCategories(p => p.includes(cat) ? p : [...p, cat]); }}>
                  + Add
                </button>
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
