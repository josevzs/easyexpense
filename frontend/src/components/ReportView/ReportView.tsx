import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { generateReport } from '../../api/client';
import { useAppStore } from '../../store/appStore';
import './ReportView.css';

export default function ReportView() {
  const { sessionId, members, allCategories } = useAppStore();
  const [tripName, setTripName] = useState('Trip Report');
  const [reportMode, setReportMode] = useState<'global' | 'personal'>('global');
  const [personalMember, setPersonalMember] = useState('');
  const [excludePersonal, setExcludePersonal] = useState(false);
  const [excludeCategories, setExcludeCategories] = useState<string[]>([]);
  const [includeCharts, setIncludeCharts] = useState(true);
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const [xlsxBase64, setXlsxBase64] = useState<string | null>(null);
  const [csvB64, setCsvB64] = useState<string | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'preview' | 'raw' | 'charts'>('preview');

  async function handleGenerate() {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const formats = ['markdown', 'pdf', 'xlsx', 'csv'];
      if (includeCharts) formats.push('html');
      const result = await generateReport(sessionId, tripName, formats, {
        report_mode: reportMode,
        personal_member: reportMode === 'personal' ? personalMember : undefined,
        exclude_personal_expenses: reportMode === 'personal' ? excludePersonal : false,
        exclude_categories: excludeCategories,
      });
      setMarkdown(result.markdown);
      setPdfBase64(result.pdf_base64);
      setXlsxBase64(result.xlsx_base64);
      setCsvB64(result.csv_b64);
      setHtml(result.html);
      setView(result.html ? 'charts' : 'preview');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Report generation failed');
    } finally {
      setLoading(false);
    }
  }

  function downloadPdf() {
    if (!pdfBase64) return;
    const bytes = atob(pdfBase64);
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([arr], { type: 'application/pdf' }));
    const a = document.createElement('a');
    a.href = url; a.download = `${tripName}.pdf`; a.click();
    URL.revokeObjectURL(url);
  }

  function downloadMd() {
    if (!markdown) return;
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }));
    const a = document.createElement('a');
    a.href = url; a.download = `${tripName}.md`; a.click();
    URL.revokeObjectURL(url);
  }

  function downloadXlsx() {
    if (!xlsxBase64) return;
    const bytes = atob(xlsxBase64);
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([arr], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }));
    const a = document.createElement('a');
    a.href = url; a.download = `${tripName}.xlsx`; a.click();
    URL.revokeObjectURL(url);
  }

  function downloadCsv() {
    if (!csvB64) return;
    const bytes = atob(csvB64);
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([arr], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url; a.download = `${tripName}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  function downloadHtml() {
    if (!html) return;
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
    const a = document.createElement('a');
    a.href = url; a.download = `${tripName}-charts.html`; a.click();
    URL.revokeObjectURL(url);
  }

  function toggleExcludeCategory(cat: string) {
    setExcludeCategories(prev =>
      prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat],
    );
  }

  const canGenerate = sessionId && (reportMode === 'global' || (reportMode === 'personal' && personalMember));

  return (
    <div className="report-view">
      <div className="report-toolbar">
        {/* Trip name */}
        <div className="report-name-row">
          <span className="field-label">TRIP NAME</span>
          <input
            type="text"
            value={tripName}
            onChange={e => setTripName(e.target.value)}
            placeholder="e.g. Greece 2024"
          />
        </div>

        {/* Mode selector */}
        <div className="report-mode-row">
          <span className="field-label">MODE</span>
          <div className="report-mode-toggle">
            <button
              className={`btn btn-sm ${reportMode === 'global' ? 'btn-fill' : ''}`}
              onClick={() => setReportMode('global')}
            >
              Global
            </button>
            <button
              className={`btn btn-sm ${reportMode === 'personal' ? 'btn-fill' : ''}`}
              onClick={() => setReportMode('personal')}
            >
              Personal
            </button>
          </div>
        </div>

        {/* Interactive charts toggle */}
        <label className="report-exclude-label">
          <input
            type="checkbox"
            checked={includeCharts}
            onChange={e => setIncludeCharts(e.target.checked)}
          />
          Include interactive charts
        </label>

        {/* Category exclusion — available in both modes */}
        {allCategories.length > 0 && (
          <div className="report-exclude-categories-row">
            <span className="field-label">EXCLUDE CATEGORIES</span>
            <div className="report-exclude-categories-list">
              {allCategories.map(cat => (
                <label key={cat} className="report-exclude-label">
                  <input
                    type="checkbox"
                    checked={excludeCategories.includes(cat)}
                    onChange={() => toggleExcludeCategory(cat)}
                  />
                  {cat}
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Personal options */}
        {reportMode === 'personal' && (
          <div className="report-personal-row">
            <select
              value={personalMember}
              onChange={e => setPersonalMember(e.target.value)}
              style={{ width: 180 }}
            >
              <option value="">— select member —</option>
              {members.map(m => (
                <option key={m.member_id} value={m.member_name}>{m.member_name}</option>
              ))}
            </select>
            <label className="report-exclude-label">
              <input
                type="checkbox"
                checked={excludePersonal}
                onChange={e => setExcludePersonal(e.target.checked)}
              />
              Exclude purely personal expenses
            </label>
          </div>
        )}

        <button className="btn btn-fill" onClick={handleGenerate} disabled={loading || !canGenerate}>
          {loading ? <span className="spinner spinner-white" /> : '↓'}
          {loading ? 'Generating…' : 'Generate Report'}
        </button>

        {markdown && (
          <div className="report-downloads">
            <button className="btn btn-sm" onClick={downloadMd}>↓ .md</button>
            <button className="btn btn-sm btn-fill" onClick={downloadPdf}>↓ .pdf</button>
            <button className="btn btn-sm" onClick={downloadXlsx}>↓ .xlsx</button>
            <button className="btn btn-sm" onClick={downloadCsv}>↓ .csv</button>
            {html && <button className="btn btn-sm" onClick={downloadHtml}>↓ .html</button>}
          </div>
        )}

        {markdown && (
          <div className="report-view-toggle">
            {html && (
              <button className={`btn btn-sm ${view === 'charts' ? 'btn-fill' : ''}`} onClick={() => setView('charts')}>Charts</button>
            )}
            <button className={`btn btn-sm ${view === 'preview' ? 'btn-fill' : ''}`} onClick={() => setView('preview')}>Preview</button>
            <button className={`btn btn-sm ${view === 'raw' ? 'btn-fill' : ''}`} onClick={() => setView('raw')}>Raw</button>
          </div>
        )}
      </div>

      {error && <div className="report-error">{error}</div>}

      {markdown && (
        <div className="report-content">
          {view === 'charts' && html ? (
            <iframe
              className="report-charts-frame"
              srcDoc={html}
              sandbox="allow-scripts"
              title="Interactive charts"
            />
          ) : view === 'preview' ? (
            <div className="md-preview">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
            </div>
          ) : (
            <pre className="md-raw">{markdown}</pre>
          )}
        </div>
      )}

      {!markdown && !loading && (
        <div className="report-empty">
          <p>
            {reportMode === 'personal' && !personalMember
              ? 'Select a member, then click Generate Report.'
              : 'Click Generate Report to render and download your expense report.'}
          </p>
        </div>
      )}
    </div>
  );
}
