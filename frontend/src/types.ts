export interface TokenItem {
  line: number;
  column: number;
  type: string;
  lexeme: string;
}

export interface SymbolItem {
  name: string;
  type: string;
  value: string;
  line: number;
}

export interface DiagnosticItem {
  level: 'ERROR' | 'WARNING' | 'INFO';
  line: number;
  column: number;
  message: string;
  suggestion?: string;
  replacement?: string;
}

export interface CompilationSummary {
  token_count: number;
  symbol_count: number;
  errors: number;
  warnings: number;
  optimization_count: number;
  status: string;
}

export interface ExecutionResult {
  success: boolean;
  output: string;
  error?: string;
  execution_type: string;
}

export interface AnalysisResponse {
  tokens: TokenItem[];
  symbols: SymbolItem[];
  diagnostics: DiagnosticItem[];
  optimizations: string[];
  corrected_code: string;
  execution?: ExecutionResult;
  summary: CompilationSummary;
}

export interface AutocompleteResponse {
  suggestions: string[];
  source: 'hybrid' | 'rule_based' | 'ai';
  active_ai: boolean;
}

export interface ExampleProgram {
  id: string;
  title: string;
  description: string;
  language: string;
  code: string;
}

export interface FixAllResponse {
  original_code: string;
  corrected_code: string;
  diff: string;
  fixed_count: number;
}

export interface ExplainFixResponse {
  explanation: string;
  fix: string;
  source: string;
}
