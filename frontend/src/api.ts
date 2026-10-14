import type { AnalysisResponse, AutocompleteResponse, ExampleProgram, FixAllResponse, ExplainFixResponse, DiagnosticItem, SymbolItem, FixDiagnosticResponse } from './types';

const API_BASE = import.meta.env.VITE_API_BASE_URL 
  ? `${import.meta.env.VITE_API_BASE_URL.replace(/\/$/, '')}/api`
  : '/api';

export const api = {
  async getHealth(): Promise<{ status: string; ai_configured: boolean; ai_provider: string }> {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error('Failed to reach backend health');
    return res.json();
  },

  async getExamples(): Promise<ExampleProgram[]> {
    const res = await fetch(`${API_BASE}/examples`);
    if (!res.ok) throw new Error('Failed to fetch examples');
    return res.json();
  },

  async analyze(source: string, language: string = 'cpp'): Promise<AnalysisResponse> {
    const res = await fetch(`${API_BASE}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, language }),
    });
    if (!res.ok) throw new Error('Analysis request failed');
    return res.json();
  },

  async autocomplete(
    prefix: string,
    suffix: string,
    line: number,
    column: number,
    language: string = 'cpp',
    symbols?: SymbolItem[],
    functions?: string[],
    signal?: AbortSignal
  ): Promise<AutocompleteResponse> {
    const res = await fetch(`${API_BASE}/autocomplete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prefix,
        suffix,
        line,
        column,
        language,
        symbols,
        functions,
      }),
      signal,
    });
    if (!res.ok) throw new Error('Autocomplete request failed');
    return res.json();
  },

  async explainAndFix(
    diagnostic: DiagnosticItem,
    codeContext: string,
    language: string = 'cpp'
  ): Promise<ExplainFixResponse> {
    const res = await fetch(`${API_BASE}/explain-fix`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        diagnostic,
        code_context: codeContext,
        language,
      }),
    });
    if (!res.ok) throw new Error('Explanation request failed');
    return res.json();
  },

  async fixDiagnostic(
    source: string,
    language: string,
    diagnostic: DiagnosticItem
  ): Promise<FixDiagnosticResponse> {
    const res = await fetch(`${API_BASE}/fix-diagnostic`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, language, diagnostic }),
    });
    if (!res.ok) throw new Error('Fix request failed');
    return res.json();
  },

  async fixAll(source: string, language: string = 'cpp'): Promise<FixAllResponse> {
    const res = await fetch(`${API_BASE}/fix-all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, language }),
    });
    if (!res.ok) throw new Error('Fix-all request failed');
    return res.json();
  },
};
