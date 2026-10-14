import React from 'react';
import { X, Check, ShieldCheck, Sparkles } from 'lucide-react';
import type { FixAllResponse } from '../types';

interface DiffPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  data: FixAllResponse | null;
  loading?: boolean;
  onAccept: (code: string) => void;
}

export const DiffPreviewModal: React.FC<DiffPreviewModalProps> = ({
  isOpen,
  onClose,
  data,
  loading,
  onAccept,
}) => {
  if (!isOpen) return null;

  // Opens instantly; shows progress until the compiler has finished checking the fix
  if (!data) {
    return (
      <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
        <div className="bg-slate-900 border border-slate-700/80 rounded-xl max-w-md w-full p-6 shadow-2xl flex items-center space-x-3">
          <Sparkles className="w-5 h-5 text-amber-300 animate-spin" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-slate-100">
              {loading ? 'Fixing your code...' : 'Preparing fixes...'}
            </p>
            <p className="text-[11px] text-slate-400">Repairing every error and re-checking it with the compiler.</p>
          </div>
          <button onClick={onClose} className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  if (data.corrected_code === data.original_code) {
    return (
      <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
        <div className="bg-slate-900 border border-slate-700/80 rounded-xl max-w-md w-full p-6 shadow-2xl">
          <div className="flex items-center space-x-2 text-emerald-300">
            <ShieldCheck className="w-5 h-5" />
            <p className="text-sm font-semibold">Nothing to fix - the compiler accepts this code.</p>
          </div>
          <div className="mt-4 flex justify-end">
            <button onClick={onClose} className="px-3 py-1.5 rounded-md text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 cursor-pointer">
              Close
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-150">
      <div className="bg-slate-900 border border-slate-700/80 rounded-xl max-w-4xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="px-5 py-4 border-b border-slate-800 bg-slate-950/70 flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <div className="w-7 h-7 rounded-md bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-300">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-100">Review Code Modifications (Fix All)</h3>
              <p className="text-[11px] text-slate-400">
                Review proposed compiler fixes before updating your editor source. Original code is preserved.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body: Diff / Split View */}
        <div className="flex-1 overflow-y-auto p-5 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
          {/* Original */}
          <div className="flex flex-col rounded-lg border border-slate-800 bg-slate-950 overflow-hidden">
            <div className="px-3 py-2 border-b border-slate-800/80 bg-rose-950/10 text-rose-300 font-semibold text-[11px] flex items-center justify-between">
              <span>Original Source</span>
              <span className="text-[10px] text-slate-500 font-mono">Unmodified</span>
            </div>
            <pre className="p-3 font-mono text-[11px] text-slate-300 whitespace-pre-wrap overflow-y-auto flex-1 max-h-[50vh]">
              {data.original_code}
            </pre>
          </div>

          {/* Corrected */}
          <div className="flex flex-col rounded-lg border border-emerald-500/30 bg-slate-950 overflow-hidden shadow-lg shadow-emerald-950/10">
            <div className="px-3 py-2 border-b border-emerald-500/20 bg-emerald-950/20 text-emerald-300 font-semibold text-[11px] flex items-center justify-between">
              <span>Proposed Corrected Source</span>
              <span className="text-[10px] text-emerald-400/80 font-mono">Validated</span>
            </div>
            <pre className="p-3 font-mono text-[11px] text-emerald-200 whitespace-pre-wrap overflow-y-auto flex-1 max-h-[50vh]">
              {data.corrected_code}
            </pre>
          </div>
        </div>

        {/* What was fixed, in plain words */}
        {data.fixes && data.fixes.length > 0 && (
          <div className="px-5 pb-3">
            <div className="text-[11px] bg-slate-950/60 p-2.5 rounded border border-slate-800">
              <p className="font-medium text-slate-300 mb-1">What was fixed ({data.fixes.length})</p>
              <ul className="list-disc pl-4 space-y-0.5 text-slate-400 max-h-28 overflow-y-auto">
                {data.fixes.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {/* Unified Diff Log (optional view) */}
        {data.diff && (
          <div className="px-5 pb-3">
            <details className="text-[11px] text-slate-400 bg-slate-950/60 p-2.5 rounded border border-slate-800">
              <summary className="cursor-pointer font-medium text-slate-300 select-none">
                View Unified Diff Patch ({data.fixed_count} adjustments)
              </summary>
              <pre className="mt-2 font-mono text-[10px] text-slate-300 whitespace-pre-wrap max-h-32 overflow-y-auto">
                {data.diff}
              </pre>
            </details>
          </div>
        )}

        {/* Modal Actions */}
        <div className="px-5 py-3 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <span className="text-[11px] text-slate-500 flex items-center space-x-1">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 inline" />
            <span>Non-destructive preview: clicking Cancel preserves your editor content intact.</span>
          </span>

          <div className="flex items-center space-x-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded-md text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 transition cursor-pointer"
            >
              Cancel & Keep Original
            </button>
            <button
              onClick={() => {
                onAccept(data.corrected_code);
                onClose();
              }}
              className="px-4 py-1.5 rounded-md text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center space-x-1.5 shadow-md shadow-emerald-950 transition cursor-pointer"
            >
              <Check className="w-3.5 h-3.5" />
              <span>Apply All Corrections</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
