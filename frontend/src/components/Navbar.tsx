import React from 'react';
import { Sparkles, Play, RotateCcw, Wand2, Sun, Moon } from 'lucide-react';
import type { ExampleProgram } from '../types';

interface NavbarProps {
  language: string;
  setLanguage: (lang: string) => void;
  onAnalyze: () => void;
  onClear: () => void;
  onFixAll: () => void;
  examples: ExampleProgram[];
  selectedExample: string;
  onSelectExample: (id: string) => void;
  aiEnabled: boolean;
  setAiEnabled: (v: boolean) => void;
  isAnalyzing: boolean;
  theme: 'dark' | 'light';
  setTheme: (t: 'dark' | 'light') => void;
  hasErrors: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({
  language,
  setLanguage,
  onAnalyze,
  onClear,
  onFixAll,
  examples,
  selectedExample,
  onSelectExample,
  aiEnabled,
  setAiEnabled,
  isAnalyzing,
  theme,
  setTheme,
  hasErrors,
}) => {
  return (
    <header className="h-14 border-b border-slate-800 bg-slate-900/90 backdrop-blur px-4 flex items-center justify-between z-20">
      {/* Brand */}
      <div className="flex items-center space-x-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-indigo-600 via-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <Sparkles className="w-4 h-4 text-white" />
        </div>
        <div>
          <span className="font-bold text-sm tracking-wide bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
            SmartCompiler
          </span>
          <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            AI 2.0 Web
          </span>
        </div>
      </div>

      {/* Middle Controls: Language & Examples */}
      <div className="flex items-center space-x-3">
        <div className="flex items-center bg-slate-950/70 border border-slate-800 rounded-md px-2.5 py-1 text-xs space-x-2">
          <span className="text-slate-400 font-medium">Lang:</span>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="bg-transparent text-slate-200 focus:outline-none cursor-pointer font-medium"
          >
            <option value="cpp" className="bg-slate-900 text-slate-200">C++ (ISO C++ / C)</option>
            <option value="c" className="bg-slate-900 text-slate-200">C (ANSI C89/C99)</option>
          </select>
        </div>

        <div className="flex items-center bg-slate-950/70 border border-slate-800 rounded-md px-2.5 py-1 text-xs space-x-2">
          <span className="text-slate-400 font-medium">Demos:</span>
          <select
            value={selectedExample}
            onChange={(e) => onSelectExample(e.target.value)}
            className="bg-transparent text-slate-200 focus:outline-none cursor-pointer max-w-[230px] truncate"
          >
            {examples.map((ex) => (
              <option key={ex.id} value={ex.id} title={ex.description} className="bg-slate-900 text-slate-200">
                {ex.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Right Controls: Actions & Settings */}
      <div className="flex items-center space-x-2.5">
        {/* AI Autocomplete Toggle Switch */}
        <button
          onClick={() => setAiEnabled(!aiEnabled)}
          title={`AI Autocomplete is ${aiEnabled ? 'ENABLED' : 'DISABLED'}`}
          className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
            aiEnabled
              ? 'bg-indigo-950/40 text-indigo-300 border-indigo-500/40 shadow-sm shadow-indigo-950'
              : 'bg-slate-800/40 text-slate-400 border-slate-700/50'
          }`}
        >
          <Sparkles className={`w-3.5 h-3.5 ${aiEnabled ? 'text-indigo-400 animate-pulse' : 'text-slate-500'}`} />
          <span>AI Ghost Text: {aiEnabled ? 'ON' : 'OFF'}</span>
        </button>

        {/* Fix All Errors */}
        <button
          onClick={onFixAll}
          disabled={!hasErrors}
          title={hasErrors ? 'Preview and Fix All Errors' : 'No errors to fix'}
          className={`flex items-center space-x-1.5 px-3 py-1 rounded-md text-xs font-semibold border transition-all ${
            hasErrors
              ? 'bg-amber-500/10 text-amber-300 border-amber-500/30 hover:bg-amber-500/20 cursor-pointer'
              : 'bg-slate-900 text-slate-600 border-slate-800 cursor-not-allowed opacity-60'
          }`}
        >
          <Wand2 className="w-3.5 h-3.5" />
          <span>Fix All Errors</span>
        </button>

        {/* Clear */}
        <button
          onClick={onClear}
          className="flex items-center space-x-1 px-2.5 py-1 rounded-md text-xs text-slate-300 hover:text-white bg-slate-800/60 hover:bg-slate-800 border border-slate-700 transition"
          title="Clear editor code"
        >
          <RotateCcw className="w-3 h-3 text-slate-400" />
          <span>Clear</span>
        </button>

        {/* Run / Analyze Button */}
        <button
          onClick={onAnalyze}
          disabled={isAnalyzing}
          className="flex items-center space-x-1.5 px-3.5 py-1 rounded-md text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shadow-md shadow-emerald-950 border border-emerald-500 transition cursor-pointer disabled:opacity-50"
        >
          <Play className="w-3.5 h-3.5 fill-current" />
          <span>{isAnalyzing ? 'Analyzing...' : 'Run / Analyze'}</span>
        </button>

        {/* Theme Toggle */}
        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-800 transition"
          title="Toggle Light/Dark Theme"
        >
          {theme === 'dark' ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
        </button>
      </div>
    </header>
  );
};
