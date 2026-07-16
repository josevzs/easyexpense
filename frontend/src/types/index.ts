export type AIProvider = 'claude' | 'openai' | 'ollama';

export type AppStep = 'upload' | 'categorize' | 'review' | 'report';

export interface Expense {
  entry_id: number;
  date: string;
  description: string;
  amount: number;
  currency: string;
  payer: string;
  is_reimbursement: boolean;
  category: string;
}

export interface Allocation {
  entry_id: number;
  participant: string;
  share: number;
  currency: string;
}

export interface Member {
  member_id: number;
  member_name: string;
  status: string;
}

export interface Balance {
  member: string;
  balance: number;
}

export interface ParsedData {
  expenses: Expense[];
  allocations: Allocation[];
  members: Member[];
  balances: Balance[];
  custom_categories: string[];
}

export interface CategorySuggestion {
  entry_id: number;
  suggested_category: string;
  confidence: number;
  reasoning: string;
  is_new_category: boolean;
}

export interface CategorizationResponse {
  suggestions: CategorySuggestion[];
  new_categories_proposed: string[];
}

export interface ProviderSettings {
  provider: AIProvider;
  claude_api_key: string;
  openai_api_key: string;
  claude_model: string;
  openai_model: string;
  ollama_model: string;
  ollama_base_url: string;
}

export interface UploadSummary {
  session_id: string;
  expense_count: number;
  member_count: number;
  date_from: string;
  date_to: string;
  total_amount: number;
  currency: string;
}

export interface ReportResponse {
  markdown: string | null;
  pdf_base64: string | null;
  xlsx_base64: string | null;
  csv_b64: string | null;
  html: string | null;
}
