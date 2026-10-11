import React, { useState } from 'react';
import type { AnalysisResponse, DiagnosticItem } from '../types';
import {
  FileCode,
  Table,
  AlertCircle,
  Zap,
  CheckCircle,
  FileText,
  Copy,
  Check,
  Wand2,
  HelpCircle,
  Info,
  Terminal,
} from 'lucide-react';

interface OutputPanelProps {
  data: AnalysisResponse | null;
  onApplyFix: (diag: DiagnosticItem) => void;
  onExplainDiag: (diag: DiagnosticItem) => void;
  onApplyCorrectedCode: (code: string) => void;
}

export const OutputPanel: React.FC<OutputPanelProps> = ({
  data,
  onApplyFix,
  onExplainDiag,
  onApplyCorrectedCode,
}) => {
  const [activeTab, setActiveTab] = useState<
    'output' | 'diagnostics' | 'tokens' | 'symbols' | 'optimizations' | 'corrected' | 'summary'
  >('output');
  const [copied, setCopied] = useState(false);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const errorCount = data?.summary.errors || 0;
  const warningCount = data?.summary.warnings || 0;
  const optCount = data?.summary.optimization_count || 0;

  return (
    <div className="flex flex-col h-full bg-slate-900 border-l border-slate-800">
      {/* Panel Tabs Header */}
      <div className="flex items-center overflow-x-auto border-b border-slate-800 bg-slate-950/60 px-2 py-1 space-x-1 shrink-0">
        {/* Terminal / Program Output Tab */}
        <button
          onClick={() => setActiveTab('output')}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-semibold transition ${
            activeTab === 'output'
              ? 'bg-slate-800 text-emerald-300 shadow-sm border-b-2 border-emerald-500'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
          }`}
        >
          <Terminal className="w-3.5 h-3.5 text-emerald-400" />
          <span>Program Output</span>
          {data?.execution && (
            <span
              className={`w-2 h-2 rounded-full ${
                data.execution.success ? 'bg-emerald-400' : 'bg-rose-400'
              }`}
            />
          )}
        </button>

        <button
          onClick={() => setActiveTab('diagnostics')}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-medium transition ${
            activeTab === 'diagnostics'
              ? 'bg-slate-800 text-white shadow-sm'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
          }`}
        >
          <AlertCircle className={`w-3.5 h-3.5 ${errorCount > 0 ? 'text-rose-400' : 'text-slate-400'}`} />
          <span>Diagnostics</span>
          {(errorCount > 0 || warningCount > 0) && (
            <span
              className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                errorCount > 0 ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'
              }`}
            >
              {errorCount + warningCount}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('tokens')}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-medium transition ${
            activeTab === 'tokens'
              ? 'bg-slate-800 text-white shadow-sm'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
          }`}
        >
          <FileCode className="w-3.5 h-3.5 text-cyan-400" />
          <span>Tokens</span>
          {data && <span className="text-[10px] text-slate-500">({data.tokens.length})</span>}
        </button>

        <button
          onClick={() => setActiveTab('symbols')}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-medium transition ${
            activeTab === 'symbols'
              ? 'bg-slate-800 text-white shadow-sm'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
          }`}
        >
          <Table className="w-3.5 h-3.5 text-purple-400" />
          <span>Symbol Table</span>
          {data && <span className="text-[10px] text-slate-500">({data.symbols.length})</span>}
        </button>

        <button
          onClick={() => setActiveTab('optimizations')}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-medium transition ${
            activeTab === 'optimizations'
              ? 'bg-slate-800 text-white shadow-sm'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
          }`}
        >
          <Zap className="w-3.5 h-3.5 text-amber-400" />
          <span>Optimization</span>
          {optCount > 0 && (
            <span className="px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300">
              {optCount}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('corrected')}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-medium transition ${
            activeTab === 'corrected'
              ? 'bg-slate-800 text-white shadow-sm'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
          }`}
        >
          <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
          <span>Corrected Code</span>
        </button>

        <button
          onClick={() => setActiveTab('summary')}
          className={`flex items-center space-x-1.5 px-3 py-1.5 rounded text-xs font-medium transition ${
            activeTab === 'summary'
              ? 'bg-slate-800 text-white shadow-sm'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
          }`}
        >
          <FileText className="w-3.5 h-3.5 text-blue-400" />
          <span>Summary</span>
        </button>
      </div>

      {/* Panel Content Body */}
      <div className="flex-1 overflow-y-auto p-4 text-xs">
        {!data ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 space-y-2">
            <Info className="w-8 h-8 text-slate-600" />
            <p>Click "Run / Analyze" to execute your program and view stdout output.</p>
          </div>
        ) : (
          <>
            {/* 0. Program Execution / Output Tab */}
            {activeTab === 'output' && (
              <div className="space-y-3 flex flex-col h-full">
                <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                  <div className="flex items-center space-x-2">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                        data.execution?.success
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                      }`}
                    >
                      {data.execution?.success ? 'Execution: Succeeded' : 'Execution: Error'}
                    </span>
                    <span className="text-slate-500 text-[11px] font-mono">
                      Engine: {data.execution?.execution_type || 'native'}
                    </span>
                  </div>

                  {data.execution?.output && (
                    <button
                      onClick={() => copyToClipboard(data.execution!.output)}
                      className="flex items-center space-x-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition cursor-pointer"
                    >
                      {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                      <span>{copied ? 'Copied' : 'Copy Output'}</span>
                    </button>
                  )}
                </div>

                {/* Console Output Terminal Screen */}
                <div className="flex-1 bg-slate-950 rounded-lg border border-slate-800 p-4 font-mono text-[13px] overflow-auto shadow-inner">
                  {data.execution?.error ? (
                    <div className="text-rose-400 whitespace-pre-wrap leading-relaxed">
                      {data.execution.error}
                    </div>
                  ) : data.execution?.output ? (
                    <div className="text-emerald-400 whitespace-pre-wrap leading-relaxed font-semibold">
                      {data.execution.output}
                    </div>
                  ) : (
                    <div className="text-slate-500 italic">
                      (No printed output. Use `print(x);` or `cout &lt;&lt; x;` to display values.)
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 1. Diagnostics Tab */}
            {activeTab === 'diagnostics' && (
              <div className="space-y-3">
                {data.diagnostics.length === 0 ? (
                  <div className="p-4 rounded-lg bg-emerald-950/20 border border-emerald-500/30 text-emerald-300 flex items-center space-x-2">
                    <CheckCircle className="w-4 h-4 text-emerald-400" />
                    <span>Clean compilation! No syntax or semantic diagnostics detected.</span>
                  </div>
                ) : (
                  data.diagnostics.map((diag, idx) => (
                    <div
                      key={idx}
                      className={`p-3 rounded-lg border transition-all ${
                        diag.level === 'ERROR'
                          ? 'bg-rose-950/20 border-rose-500/30 hover:border-rose-500/50'
                          : 'bg-amber-950/20 border-amber-500/30 hover:border-amber-500/50'
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-center space-x-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              diag.level === 'ERROR'
                                ? 'bg-rose-500/20 text-rose-300'
                                : 'bg-amber-500/20 text-amber-300'
                            }`}
                          >
                            {diag.level}
                          </span>
                          <span className="font-mono text-slate-300">
                            Line {diag.line}:{diag.column || 1}
                          </span>
                        </div>

                        {/* Action buttons */}
                        <div className="flex items-center space-x-1.5">
                          <button
                            onClick={() => onExplainDiag(diag)}
                            className="px-2 py-0.8 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center space-x-1 transition cursor-pointer"
                            title="Explain diagnostic with AI"
                          >
                            <HelpCircle className="w-3 h-3 text-cyan-400" />
                            <span>Explain</span>
                          </button>
                          {diag.suggestion && (
                            <button
                              onClick={() => onApplyFix(diag)}
                              className="px-2 py-0.8 rounded bg-indigo-600 hover:bg-indigo-500 text-white flex items-center space-x-1 transition cursor-pointer"
                              title="Apply fix to code"
                            >
                              <Wand2 className="w-3 h-3" />
                              <span>Apply Fix</span>
                            </button>
                          )}
                        </div>
                      </div>

                      <p className="mt-2 text-slate-200 font-medium">{diag.message}</p>

                      {diag.suggestion && (
                        <div className="mt-2 p-2 rounded bg-slate-950/80 border border-slate-800/80 font-mono text-[11px] text-slate-300">
                          <span className="text-slate-500 select-none">Suggestion: </span>
                          <span className="text-emerald-400">{diag.suggestion}</span>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}

            {/* 2. Tokens Tab */}
            {activeTab === 'tokens' && (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400 font-semibold">
                      <th className="py-2 px-3">Line</th>
                      <th className="py-2 px-3">Column</th>
                      <th className="py-2 px-3">Token Type</th>
                      <th className="py-2 px-3">Lexeme</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                    {data.tokens.map((tok, i) => (
                      <tr key={i} className="hover:bg-slate-800/30">
                        <td className="py-1.5 px-3 text-slate-500">{tok.line}</td>
                        <td className="py-1.5 px-3 text-slate-500">{tok.column}</td>
                        <td className="py-1.5 px-3">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                              tok.type === 'KEYWORD'
                                ? 'bg-indigo-500/20 text-indigo-300'
                                : tok.type === 'IDENTIFIER'
                                ? 'bg-cyan-500/20 text-cyan-300'
                                : tok.type === 'OPERATOR'
                                ? 'bg-amber-500/20 text-amber-300'
                                : tok.type === 'DELIMITER'
                                ? 'bg-slate-700 text-slate-300'
                                : 'bg-emerald-500/20 text-emerald-300'
                            }`}
                          >
                            {tok.type}
                          </span>
                        </td>
                        <td className="py-1.5 px-3 text-slate-200">{tok.lexeme}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* 3. Symbol Table Tab */}
            {activeTab === 'symbols' && (
              <div className="overflow-x-auto">
                {data.symbols.length === 0 ? (
                  <p className="text-slate-500">No symbols registered in scope.</p>
                ) : (
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-400 font-semibold">
                        <th className="py-2 px-3">Identifier</th>
                        <th className="py-2 px-3">Data Type</th>
                        <th className="py-2 px-3">Resolved Value</th>
                        <th className="py-2 px-3">Declared Line</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                      {data.symbols.map((sym, i) => (
                        <tr key={i} className="hover:bg-slate-800/30">
                          <td className="py-2 px-3 text-cyan-300 font-bold">{sym.name}</td>
                          <td className="py-2 px-3 text-indigo-400">{sym.type}</td>
                          <td className="py-2 px-3 text-slate-200">{sym.value}</td>
                          <td className="py-2 px-3 text-slate-500">Line {sym.line}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {/* 4. Optimization Tab */}
            {activeTab === 'optimizations' && (
              <div className="space-y-2">
                <div className="p-3 bg-slate-950/80 rounded-lg border border-slate-800 text-slate-400">
                  <h4 className="font-semibold text-slate-200 mb-1">Early AST & Intermediate Optimization Passes:</h4>
                  <p className="text-[11px]">
                    Includes Constant Folding, Constant Propagation, Algebraic Simplification, Strength Reduction, and Common Subexpression Detection.
                  </p>
                </div>

                {data.optimizations.length === 0 ? (
                  <p className="text-slate-500 p-2">No optimization opportunities found in current code.</p>
                ) : (
                  data.optimizations.map((opt, i) => (
                    <div
                      key={i}
                      className="p-2.5 rounded bg-amber-950/15 border border-amber-500/20 font-mono text-[11px] text-amber-200 flex items-start space-x-2"
                    >
                      <Zap className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                      <span>{opt}</span>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* 5. Corrected Code Tab */}
            {activeTab === 'corrected' && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 text-[11px]">
                    Syntactically and semantically corrected version generated by compiler:
                  </span>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => copyToClipboard(data.corrected_code)}
                      className="flex items-center space-x-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition cursor-pointer"
                    >
                      {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                      <span>{copied ? 'Copied' : 'Copy'}</span>
                    </button>
                    <button
                      onClick={() => onApplyCorrectedCode(data.corrected_code)}
                      className="flex items-center space-x-1 px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium transition cursor-pointer"
                    >
                      <CheckCircle className="w-3 h-3" />
                      <span>Accept & Replace Editor</span>
                    </button>
                  </div>
                </div>

                <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[12px] text-emerald-300/90 whitespace-pre-wrap overflow-x-auto leading-relaxed">
                  {data.corrected_code}
                </pre>
              </div>
            )}

            {/* 6. Compilation Summary */}
            {activeTab === 'summary' && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                    <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider">Tokens</span>
                    <div className="text-xl font-bold text-slate-100 mt-1">{data.summary.token_count}</div>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                    <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider">Symbols</span>
                    <div className="text-xl font-bold text-cyan-400 mt-1">{data.summary.symbol_count}</div>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                    <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider">Errors</span>
                    <div className="text-xl font-bold text-rose-400 mt-1">{data.summary.errors}</div>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                    <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider">Warnings</span>
                    <div className="text-xl font-bold text-amber-400 mt-1">{data.summary.warnings}</div>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                    <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider">Optimizations</span>
                    <div className="text-xl font-bold text-emerald-400 mt-1">{data.summary.optimization_count}</div>
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                  <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider">Compiler Status</span>
                  <div className="text-sm font-medium text-slate-200 mt-1">{data.summary.status}</div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};
