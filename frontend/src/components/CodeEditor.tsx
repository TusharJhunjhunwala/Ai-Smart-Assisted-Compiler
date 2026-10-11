import React, { useRef, useEffect, useState, useCallback } from 'react';
import Editor from '@monaco-editor/react';
import type { Monaco, OnMount } from '@monaco-editor/react';
import type { editor } from 'monaco-editor';
import { api } from '../api';
import type { DiagnosticItem, SymbolItem } from '../types';
import { Sparkles, Check, X, ChevronRight, ChevronLeft } from 'lucide-react';

interface CodeEditorProps {
  code: string;
  onChange: (value: string) => void;
  language: string;
  theme: 'dark' | 'light';
  aiEnabled: boolean;
  diagnostics: DiagnosticItem[];
  symbols: SymbolItem[];
  onCursorChange?: (line: number, col: number) => void;
  activeGhostText: string | null;
  setActiveGhostText: (t: string | null) => void;
}

export const CodeEditor: React.FC<CodeEditorProps> = ({
  code,
  onChange,
  language,
  theme,
  aiEnabled,
  diagnostics,
  symbols,
  onCursorChange,
  activeGhostText,
  setActiveGhostText,
}) => {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const debounceTimerRef = useRef<any>(null);

  // Suggestions history & cycling
  const [suggestionList, setSuggestionList] = useState<string[]>([]);
  const [suggestionIndex, setSuggestionIndex] = useState<number>(0);

  // Keep refs to avoid closure staleness in keyboard handlers
  const ghostTextRef = useRef<string | null>(activeGhostText);
  const suggestionListRef = useRef<string[]>(suggestionList);
  const suggestionIndexRef = useRef<number>(suggestionIndex);

  useEffect(() => {
    ghostTextRef.current = activeGhostText;
  }, [activeGhostText]);

  useEffect(() => {
    suggestionListRef.current = suggestionList;
  }, [suggestionList]);

  useEffect(() => {
    suggestionIndexRef.current = suggestionIndex;
  }, [suggestionIndex]);

  // Method to accept current ghost text
  const acceptSuggestion = useCallback(() => {
    const textToInsert = ghostTextRef.current;
    if (!textToInsert || !editorRef.current || !monacoRef.current) return false;

    const editor = editorRef.current;
    const position = editor.getPosition();
    if (!position) return false;

    // Insert the text directly at cursor position
    editor.executeEdits('ai-ghost-text', [
      {
        range: new monacoRef.current.Range(
          position.lineNumber,
          position.column,
          position.lineNumber,
          position.column
        ),
        text: textToInsert,
        forceMoveMarkers: true,
      },
    ]);

    // Focus editor and clear suggestion state
    editor.focus();
    setActiveGhostText(null);
    setSuggestionList([]);
    return true;
  }, [setActiveGhostText]);

  // Method to dismiss suggestion
  const dismissSuggestion = useCallback(() => {
    setActiveGhostText(null);
    setSuggestionList([]);
  }, [setActiveGhostText]);

  // Cycle to next suggestion
  const cycleNext = useCallback(() => {
    const list = suggestionListRef.current;
    if (list.length <= 1) return;
    const nextIdx = (suggestionIndexRef.current + 1) % list.length;
    setSuggestionIndex(nextIdx);
    setActiveGhostText(list[nextIdx]);
  }, [setActiveGhostText]);

  // Cycle to previous suggestion
  const cyclePrev = useCallback(() => {
    const list = suggestionListRef.current;
    if (list.length <= 1) return;
    const prevIdx = (suggestionIndexRef.current - 1 + list.length) % list.length;
    setSuggestionIndex(prevIdx);
    setActiveGhostText(list[prevIdx]);
  }, [setActiveGhostText]);

  // Handle editor mount
  const handleEditorDidMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    // Set cursor position tracking
    editor.onDidChangeCursorPosition((e) => {
      onCursorChange?.(e.position.lineNumber, e.position.column);
    });

    // Intercept keyboard events in Monaco's input pipeline
    editor.onKeyDown((e) => {
      // 1. Tab accepts
      if (e.keyCode === monaco.KeyCode.Tab) {
        if (ghostTextRef.current) {
          e.preventDefault();
          e.stopPropagation();
          acceptSuggestion();
          return;
        }
      }

      // 2. Escape dismisses
      if (e.keyCode === monaco.KeyCode.Escape) {
        if (ghostTextRef.current) {
          e.preventDefault();
          e.stopPropagation();
          dismissSuggestion();
          return;
        }
      }

      // 3. Alt + ] or Alt + [ or Alt + Down / Alt + Up to cycle suggestions
      if (e.altKey && (e.keyCode === monaco.KeyCode.BracketRight || e.keyCode === monaco.KeyCode.DownArrow)) {
        if (suggestionListRef.current.length > 1) {
          e.preventDefault();
          e.stopPropagation();
          cycleNext();
          return;
        }
      }

      if (e.altKey && (e.keyCode === monaco.KeyCode.BracketLeft || e.keyCode === monaco.KeyCode.UpArrow)) {
        if (suggestionListRef.current.length > 1) {
          e.preventDefault();
          e.stopPropagation();
          cyclePrev();
          return;
        }
      }
    });

    // Global Monaco actions as backup
    editor.addAction({
      id: 'accept-ai-suggestion',
      label: 'Accept AI Suggestion',
      keybindings: [monaco.KeyCode.Tab],
      run: () => {
        if (ghostTextRef.current) acceptSuggestion();
      },
    });

    editor.addAction({
      id: 'cycle-next-ai-suggestion',
      label: 'Next AI Suggestion',
      keybindings: [monaco.KeyMod.Alt | monaco.KeyCode.BracketRight, monaco.KeyMod.Alt | monaco.KeyCode.DownArrow],
      run: () => {
        cycleNext();
      },
    });

    editor.addAction({
      id: 'cycle-prev-ai-suggestion',
      label: 'Previous AI Suggestion',
      keybindings: [monaco.KeyMod.Alt | monaco.KeyCode.BracketLeft, monaco.KeyMod.Alt | monaco.KeyCode.UpArrow],
      run: () => {
        cyclePrev();
      },
    });
  };

  // Trigger Debounced Autocomplete
  const triggerAutocomplete = (updatedCode?: string) => {
    if (!aiEnabled || !editorRef.current) {
      setActiveGhostText(null);
      return;
    }

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    debounceTimerRef.current = setTimeout(async () => {
      if (!editorRef.current) return;
      const position = editorRef.current.getPosition();
      if (!position) return;

      const model = editorRef.current.getModel();
      if (!model) return;

      const currentOffset = model.getOffsetAt(position);
      const fullText = updatedCode !== undefined ? updatedCode : model.getValue();
      const prefix = fullText.slice(0, currentOffset);
      const suffix = fullText.slice(currentOffset);

      if (!prefix.trim()) {
        setActiveGhostText(null);
        return;
      }

      abortControllerRef.current = new AbortController();
      try {
        const res = await api.autocomplete(
          prefix,
          suffix,
          position.lineNumber,
          position.column,
          language,
          symbols,
          undefined,
          abortControllerRef.current.signal
        );

        if (res && res.suggestions && res.suggestions.length > 0) {
          setSuggestionList(res.suggestions);
          setSuggestionIndex(0);
          setActiveGhostText(res.suggestions[0]);
        } else {
          setActiveGhostText(null);
          setSuggestionList([]);
        }
      } catch (err: any) {
        if (err.name !== 'AbortError') {
          console.error('Autocomplete error:', err);
        }
      }
    }, 200);
  };

  // Sync Diagnostics Markers with Monaco Editor
  useEffect(() => {
    if (!editorRef.current || !monacoRef.current) return;
    const model = editorRef.current.getModel();
    if (!model) return;

    const markers: editor.IMarkerData[] = diagnostics.map((d) => {
      const severity =
        d.level === 'ERROR'
          ? monacoRef.current!.MarkerSeverity.Error
          : d.level === 'WARNING'
          ? monacoRef.current!.MarkerSeverity.Warning
          : monacoRef.current!.MarkerSeverity.Info;

      const lineContent = model.getLineContent(d.line) || '';
      return {
        severity,
        startLineNumber: d.line,
        startColumn: d.column || 1,
        endLineNumber: d.line,
        endColumn: Math.max((d.column || 1) + 4, lineContent.length + 1),
        message: d.message + (d.suggestion ? ` (${d.suggestion})` : ''),
      };
    });

    monacoRef.current.editor.setModelMarkers(model, 'compiler', markers);
  }, [diagnostics]);

  return (
    <div className="relative w-full h-full flex flex-col bg-slate-950 overflow-hidden">
      {/* Editor Main */}
      <div className="flex-1 relative">
        <Editor
          height="100%"
          language={language === 'c' ? 'c' : 'cpp'}
          theme={theme === 'dark' ? 'vs-dark' : 'light'}
          value={code}
          onChange={(val) => {
            const nextVal = val || '';
            onChange(nextVal);
            triggerAutocomplete(nextVal);
          }}
          onMount={handleEditorDidMount}
          options={{
            fontSize: 14,
            fontFamily: "'Fira Code', 'Cascadia Code', Menlo, monospace",
            fontLigatures: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            lineNumbers: 'on',
            automaticLayout: true,
            tabSize: 4,
            insertSpaces: true,
            renderLineHighlight: 'all',
            cursorBlinking: 'smooth',
            cursorSmoothCaretAnimation: 'on',
            smoothScrolling: true,
            suggestOnTriggerCharacters: true,
            quickSuggestions: false,
          }}
        />

        {/* Floating Copilot-style Ghost Suggestion Banner when active */}
        {activeGhostText && (
          <div className="absolute bottom-4 left-6 right-6 bg-slate-900/95 border-2 border-indigo-500/80 rounded-xl p-3.5 shadow-2xl backdrop-blur flex flex-col sm:flex-row sm:items-center justify-between gap-3 z-30 transition-all animate-in fade-in slide-in-from-bottom-2 ring-4 ring-indigo-500/10">
            <div className="flex items-start space-x-3 overflow-hidden">
              <div className="p-1.5 rounded-lg bg-indigo-500/20 text-indigo-400 mt-0.5 shrink-0 animate-pulse">
                <Sparkles className="w-4 h-4" />
              </div>
              <div className="text-xs">
                <div className="flex items-center space-x-2">
                  <span className="font-bold text-indigo-300">Predictive Ghost Completion:</span>
                  <span className="px-1.5 py-0.5 rounded bg-indigo-950 border border-indigo-500/40 text-[10px] font-mono text-indigo-200">
                    Press TAB to accept
                  </span>
                  {suggestionList.length > 1 && (
                    <div className="flex items-center space-x-1 bg-slate-800 px-1.5 py-0.5 rounded border border-slate-700">
                      <span className="text-[10px] text-slate-300">
                        {suggestionIndex + 1} of {suggestionList.length}
                      </span>
                      <button
                        onClick={cyclePrev}
                        className="p-0.5 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition cursor-pointer"
                        title="Previous suggestion (Alt + [ or Alt + Up)"
                      >
                        <ChevronLeft className="w-3 h-3" />
                      </button>
                      <button
                        onClick={cycleNext}
                        className="p-0.5 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition cursor-pointer"
                        title="Next suggestion (Alt + ] or Alt + Down)"
                      >
                        <ChevronRight className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                </div>
                <pre className="text-slate-100 font-mono mt-2 whitespace-pre-wrap max-h-28 overflow-y-auto bg-slate-950 px-3 py-2 rounded-lg border border-slate-800 text-[12px] leading-relaxed select-none shadow-inner">
                  {activeGhostText}
                </pre>
              </div>
            </div>

            <div className="flex items-center space-x-2 shrink-0 self-end sm:self-center">
              <button
                onClick={() => acceptSuggestion()}
                className="flex items-center space-x-1.5 px-3.5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-lg shadow-indigo-600/30 transition cursor-pointer"
                title="Accept suggestion (Tab)"
              >
                <Check className="w-3.5 h-3.5" />
                <span>Accept (Tab)</span>
              </button>
              <button
                onClick={() => dismissSuggestion()}
                className="flex items-center space-x-1 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition cursor-pointer"
                title="Dismiss suggestion (Esc)"
              >
                <X className="w-3.5 h-3.5" />
                <span>Dismiss (Esc)</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
