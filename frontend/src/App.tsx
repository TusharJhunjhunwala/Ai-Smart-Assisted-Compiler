import React, { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { CodeEditor } from './components/CodeEditor';
import { OutputPanel } from './components/OutputPanel';
import { AIAssistantPanel } from './components/AIAssistantPanel';
import { DiffPreviewModal } from './components/DiffPreviewModal';
import { StatusBar } from './components/StatusBar';
import { api } from './api';
import type {
  AnalysisResponse,
  DiagnosticItem,
  ExampleProgram,
  ExplainFixResponse,
  FixAllResponse,
} from './types';

export const App: React.FC = () => {
  const [language, setLanguage] = useState<string>('cpp');
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [code, setCode] = useState<string>('');
  const [examples, setExamples] = useState<ExampleProgram[]>([]);
  const [selectedExampleId, setSelectedExampleId] = useState<string>('errors_and_opt');
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [analysisData, setAnalysisData] = useState<AnalysisResponse | null>(null);

  // AI & Ghost text
  const [aiEnabled, setAiEnabled] = useState<boolean>(true);
  const [activeGhostText, setActiveGhostText] = useState<string | null>(null);
  const [aiConfigured, setAiConfigured] = useState<boolean>(false);
  const [aiProvider, setAiProvider] = useState<string>('offline_rule_engine');

  // AI Assistant Panel State
  const [isAiPanelOpen, setIsAiPanelOpen] = useState<boolean>(false);
  const [activeDiagnostic, setActiveDiagnostic] = useState<DiagnosticItem | null>(null);
  const [explanationData, setExplanationData] = useState<ExplainFixResponse | null>(null);
  const [isExplaining, setIsExplaining] = useState<boolean>(false);

  // Fix All Diff Modal
  const [isDiffModalOpen, setIsDiffModalOpen] = useState<boolean>(false);
  const [diffData, setDiffData] = useState<FixAllResponse | null>(null);

  // Status bar
  const [cursorPos, setCursorPos] = useState<{ line: number; col: number }>({ line: 1, col: 1 });
  const [statusMessage, setStatusMessage] = useState<string>('Ready');

  // Initial load
  useEffect(() => {
    // Check Health
    api.getHealth()
      .then((h) => {
        setAiConfigured(h.ai_configured);
        setAiProvider(h.ai_provider);
      })
      .catch((e) => console.warn('Backend not ready yet:', e));

    // Load Examples
    api.getExamples()
      .then((exs) => {
        setExamples(exs);
        const defaultEx = exs.find((e) => e.id === 'errors_and_opt') || exs[0];
        if (defaultEx) {
          setCode(defaultEx.code);
          setSelectedExampleId(defaultEx.id);
        }
      })
      .catch((e) => console.warn('Examples load error:', e));
  }, []);

  // Run Compiler Analysis
  const handleAnalyze = async () => {
    if (!code.trim()) {
      setStatusMessage('Warning: Code is empty.');
      return;
    }
    setIsAnalyzing(true);
    setStatusMessage('Analyzing program syntax & semantics...');
    try {
      const res = await api.analyze(code, language);
      setAnalysisData(res);
      setStatusMessage(
        `Analysis complete: ${res.summary.errors} error(s), ${res.summary.warnings} warning(s), ${res.summary.optimization_count} optimization(s).`
      );
    } catch (err) {
      console.error(err);
      setStatusMessage('Error executing compiler analysis.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  // Switch Example
  const handleSelectExample = (id: string) => {
    setSelectedExampleId(id);
    const ex = examples.find((e) => e.id === id);
    if (ex) {
      setCode(ex.code);
      setAnalysisData(null);
      setActiveGhostText(null);
      setStatusMessage(`Loaded example: ${ex.title}. Click Run / Analyze.`);
    }
  };

  // Clear Editor
  const handleClear = () => {
    setCode('');
    setAnalysisData(null);
    setActiveGhostText(null);
    setStatusMessage('Editor cleared.');
  };

  // Explain Diagnostic with AI
  const handleExplainDiagnostic = async (diag: DiagnosticItem) => {
    setActiveDiagnostic(diag);
    setIsAiPanelOpen(true);
    setIsExplaining(true);
    try {
      const res = await api.explainAndFix(diag, code, language);
      setExplanationData(res);
    } catch (err) {
      console.error(err);
    } finally {
      setIsExplaining(false);
    }
  };

  // Apply single diagnostic fix
  const handleApplySingleFix = (diag: DiagnosticItem) => {
    if (diag.replacement) {
      // Replace in code directly
      const lines = code.split('\n');
      if (diag.line <= lines.length) {
        lines[diag.line - 1] = diag.replacement;
        const newCode = lines.join('\n');
        setCode(newCode);
        setStatusMessage(`Applied fix for diagnostic on Line ${diag.line}.`);
        return;
      }
    }
    // Fallback if no direct replacement: trigger fix-all or inform
    setStatusMessage(`Use Fix All Errors or manually review suggestion: ${diag.suggestion}`);
  };

  // Trigger Fix All Preview Modal
  const handleFixAll = async () => {
    if (!code.trim()) return;
    setStatusMessage('Generating non-destructive fix patch...');
    try {
      const res = await api.fixAll(code, language);
      setDiffData(res);
      setIsDiffModalOpen(true);
      setStatusMessage('Reviewing proposed code fixes.');
    } catch (err) {
      console.error(err);
      setStatusMessage('Failed to generate fix diff.');
    }
  };

  const lineCount = code ? code.split('\n').length : 1;
  const errorCount = analysisData?.summary.errors || 0;
  const warningCount = analysisData?.summary.warnings || 0;

  return (
    <div className={`flex flex-col h-screen w-screen overflow-hidden ${theme === 'dark' ? 'dark bg-slate-950 text-slate-100' : 'bg-slate-50 text-slate-900'}`}>
      {/* Top Navbar */}
      <Navbar
        language={language}
        setLanguage={setLanguage}
        onAnalyze={handleAnalyze}
        onClear={handleClear}
        onFixAll={handleFixAll}
        examples={examples}
        selectedExample={selectedExampleId}
        onSelectExample={handleSelectExample}
        aiEnabled={aiEnabled}
        setAiEnabled={setAiEnabled}
        isAnalyzing={isAnalyzing}
        theme={theme}
        setTheme={setTheme}
        hasErrors={errorCount > 0}
      />

      {/* Main Workspace */}
      <div className="flex-1 flex overflow-hidden">
        {/* Central Monaco Editor */}
        <div className="flex-1 h-full min-w-[320px]">
          <CodeEditor
            code={code}
            onChange={setCode}
            language={language}
            theme={theme}
            aiEnabled={aiEnabled}
            diagnostics={analysisData?.diagnostics || []}
            symbols={analysisData?.symbols || []}
            onCursorChange={(line, col) => setCursorPos({ line, col })}
            activeGhostText={activeGhostText}
            setActiveGhostText={setActiveGhostText}
          />
        </div>

        {/* Output Panel (Tokens, Symbols, Diagnostics, Optimization, Corrected Code, Summary) */}
        <div className="w-[45%] max-w-[680px] min-w-[380px] h-full">
          <OutputPanel
            data={analysisData}
            onApplyFix={handleApplySingleFix}
            onExplainDiag={handleExplainDiagnostic}
            onApplyCorrectedCode={(newCode) => {
              setCode(newCode);
              setStatusMessage('Editor updated with compiler-corrected code.');
            }}
          />
        </div>

        {/* AI Assistant Sidebar Panel */}
        <AIAssistantPanel
          isOpen={isAiPanelOpen}
          onClose={() => setIsAiPanelOpen(false)}
          activeDiag={activeDiagnostic}
          explanationData={explanationData}
          isLoading={isExplaining}
          onApplyFix={(fixSnippet) => {
            if (activeDiagnostic) {
              const lines = code.split('\n');
              if (activeDiagnostic.line <= lines.length) {
                lines[activeDiagnostic.line - 1] = fixSnippet;
                setCode(lines.join('\n'));
                setIsAiPanelOpen(false);
                setStatusMessage(`Applied AI fix on line ${activeDiagnostic.line}.`);
              }
            }
          }}
          aiConfigured={aiConfigured}
          aiProvider={aiProvider}
        />
      </div>

      {/* Diff Preview Modal (Fix All) */}
      <DiffPreviewModal
        isOpen={isDiffModalOpen}
        onClose={() => setIsDiffModalOpen(false)}
        data={diffData}
        onAccept={(correctedCode) => {
          setCode(correctedCode);
          setStatusMessage('Accepted all proposed compiler corrections.');
        }}
      />

      {/* Status Bar */}
      <StatusBar
        language={language}
        lineCount={lineCount}
        cursorPos={cursorPos}
        status={statusMessage}
        errorCount={errorCount}
        warningCount={warningCount}
        aiActive={aiConfigured}
      />
    </div>
  );
};

export default App;
