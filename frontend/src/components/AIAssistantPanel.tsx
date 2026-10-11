import React from 'react';
import { Sparkles, Bot, CheckCircle, Lightbulb, X, Wand2 } from 'lucide-react';
import type { ExplainFixResponse, DiagnosticItem } from '../types';

interface AIAssistantPanelProps {
  isOpen: boolean;
  onClose: () => void;
  activeDiag: DiagnosticItem | null;
  explanationData: ExplainFixResponse | null;
  isLoading: boolean;
  onApplyFix: (fixCode: string) => void;
  aiConfigured: boolean;
  aiProvider: string;
}

export const AIAssistantPanel: React.FC<AIAssistantPanelProps> = ({
  isOpen,
  onClose,
  activeDiag,
  explanationData,
  isLoading,
  onApplyFix,
  aiConfigured,
  aiProvider,
}) => {
  if (!isOpen) return null;

  return (
    <div className="w-80 border-l border-slate-800 bg-slate-900/95 flex flex-col h-full z-10 shrink-0">
      {/* Panel Header */}
      <div className="h-12 border-b border-slate-800 px-4 flex items-center justify-between bg-slate-950/70">
        <div className="flex items-center space-x-2">
          <Bot className="w-4 h-4 text-indigo-400" />
          <span className="font-semibold text-xs text-slate-200">AI Diagnostic Assistant</span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Engine Status Tag */}
      <div className="px-4 py-2 border-b border-slate-800/80 bg-slate-950/30 flex items-center justify-between text-[11px]">
        <span className="text-slate-400">Intelligence Engine:</span>
        <span
          className={`font-medium px-2 py-0.5 rounded text-[10px] ${
            aiConfigured
              ? 'bg-indigo-500/10 text-indigo-300 border border-indigo-500/30'
              : 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/30'
          }`}
        >
          {aiConfigured ? `Cloud LLM (${aiProvider})` : 'Offline Rule Engine'}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400 space-y-3">
            <Sparkles className="w-6 h-6 text-indigo-400 animate-spin" />
            <p>Consulting compiler heuristics & intelligence model...</p>
          </div>
        ) : activeDiag && explanationData ? (
          <div className="space-y-4">
            {/* Target Diagnostic */}
            <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
              <div className="flex items-center space-x-2 mb-1">
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                    activeDiag.level === 'ERROR'
                      ? 'bg-rose-500/20 text-rose-300'
                      : 'bg-amber-500/20 text-amber-300'
                  }`}
                >
                  {activeDiag.level}
                </span>
                <span className="text-slate-400 font-mono">Line {activeDiag.line}</span>
              </div>
              <p className="font-semibold text-slate-200">{activeDiag.message}</p>
            </div>

            {/* Explanation */}
            <div className="p-3.5 rounded-lg bg-indigo-950/20 border border-indigo-500/30 space-y-2">
              <div className="flex items-center space-x-1.5 text-indigo-300 font-medium">
                <Lightbulb className="w-3.5 h-3.5 text-indigo-400" />
                <span>Problem Analysis</span>
              </div>
              <p className="text-slate-300 leading-relaxed text-[11px] whitespace-pre-wrap">
                {explanationData.explanation}
              </p>
            </div>

            {/* Recommended Fix */}
            {explanationData.fix && (
              <div className="p-3.5 rounded-lg bg-emerald-950/20 border border-emerald-500/30 space-y-2.5">
                <div className="flex items-center space-x-1.5 text-emerald-300 font-medium">
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Proposed Resolution</span>
                </div>
                <pre className="p-2.5 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-emerald-300 whitespace-pre-wrap">
                  {explanationData.fix}
                </pre>
                <button
                  onClick={() => onApplyFix(explanationData.fix)}
                  className="w-full py-1.5 px-3 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium flex items-center justify-center space-x-1.5 shadow-md shadow-emerald-950 transition cursor-pointer"
                >
                  <Wand2 className="w-3.5 h-3.5" />
                  <span>Apply Recommended Fix</span>
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-16 text-slate-500 text-center space-y-2">
            <Bot className="w-8 h-8 text-slate-600" />
            <p>Select any diagnostic from the Diagnostics tab to request an in-depth AI explanation and recommended code correction.</p>
          </div>
        )}
      </div>
    </div>
  );
};
