import React from 'react';
import { Terminal, AlertCircle, Sparkles } from 'lucide-react';

interface StatusBarProps {
  language: string;
  lineCount: number;
  cursorPos: { line: number; col: number };
  status: string;
  errorCount: number;
  warningCount: number;
  aiActive: boolean;
}

export const StatusBar: React.FC<StatusBarProps> = ({
  language,
  lineCount,
  cursorPos,
  status,
  errorCount,
  warningCount,
  aiActive,
}) => {
  return (
    <footer className="h-6 bg-slate-950 border-t border-slate-800 px-3 flex items-center justify-between text-[11px] text-slate-400 select-none z-20">
      {/* Left indicators */}
      <div className="flex items-center space-x-3">
        <div className="flex items-center space-x-1 font-medium text-slate-300">
          <Terminal className="w-3 h-3 text-indigo-400" />
          <span>{status}</span>
        </div>

        {/* Errors & Warnings counter */}
        <div className="flex items-center space-x-2 pl-2 border-l border-slate-800">
          <span className="flex items-center space-x-1 text-rose-400">
            <AlertCircle className="w-3 h-3" />
            <span>{errorCount}</span>
          </span>
          <span className="flex items-center space-x-1 text-amber-400">
            <span>{warningCount} warnings</span>
          </span>
        </div>
      </div>

      {/* Right indicators */}
      <div className="flex items-center space-x-4">
        {/* AI status */}
        <div className="flex items-center space-x-1.5 text-slate-400">
          <Sparkles className={`w-3 h-3 ${aiActive ? 'text-indigo-400' : 'text-slate-600'}`} />
          <span>AI Assistant: {aiActive ? 'Active' : 'Offline Engine'}</span>
        </div>

        {/* Cursor & Lines */}
        <div className="pl-3 border-l border-slate-800 text-slate-300 font-mono">
          <span>Ln {cursorPos.line}, Col {cursorPos.col}</span>
          <span className="text-slate-600 ml-2">({lineCount} lines)</span>
        </div>

        {/* Encoding / Lang */}
        <div className="pl-3 border-l border-slate-800 uppercase font-semibold text-slate-400">
          {language} • UTF-8
        </div>
      </div>
    </footer>
  );
};
