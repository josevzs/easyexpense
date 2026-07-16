import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type {
  AppStep, Expense, CategorySuggestion, ProviderSettings,
  UploadSummary, ParsedData,
} from '../types';

const DEFAULT_SETTINGS: ProviderSettings = {
  provider: 'ollama',
  claude_api_key: '',
  openai_api_key: '',
  claude_model: 'claude-sonnet-4-6',
  openai_model: 'gpt-4o-mini',
  ollama_model: 'llama3.2',
  ollama_base_url: 'http://localhost:11434',
};

interface AppState {
  // Session
  sessionId: string | null;
  uploadSummary: UploadSummary | null;

  // Data
  expenses: Expense[];
  allCategories: string[];
  customCategories: string[];
  members: { member_id: number; member_name: string; status: string }[];
  balances: { member: string; balance: number }[];

  // Suggestions
  suggestions: CategorySuggestion[];
  newCategoriesProposed: string[];

  // UI
  currentStep: AppStep;
  isLoadingAI: boolean;
  error: string | null;

  // Settings — persisted to localStorage
  settings: ProviderSettings;

  // Cached inputs — persisted to localStorage
  lastRegistryInput: string;

  // Actions
  setSessionId: (id: string) => void;
  setUploadSummary: (s: UploadSummary) => void;
  setData: (data: ParsedData) => void;
  setExpenses: (expenses: Expense[]) => void;
  patchExpenseCategory: (entryId: number, category: string) => void;
  setSuggestions: (suggestions: CategorySuggestion[], newCats: string[]) => void;
  applySuggestion: (entryId: number, category: string) => void;
  applyAllSuggestions: (minConfidence?: number) => Array<{ entry_id: number; category: string }>;
  addCustomCategory: (cat: string) => void;
  setStep: (step: AppStep) => void;
  setLoadingAI: (v: boolean) => void;
  setError: (msg: string | null) => void;
  setSettings: (s: ProviderSettings) => void;
  setLastRegistryInput: (v: string) => void;
  reset: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      sessionId: null,
      uploadSummary: null,
      expenses: [],
      allCategories: [],
      customCategories: [],
      members: [],
      balances: [],
      suggestions: [],
      newCategoriesProposed: [],
      currentStep: 'upload',
      isLoadingAI: false,
      error: null,
      settings: DEFAULT_SETTINGS,
      lastRegistryInput: '',

      setSessionId: (id) => set({ sessionId: id }),
      setUploadSummary: (s) => set({ uploadSummary: s }),

      setData: (data) => {
        const presets = [
          'Estancias', 'Alquiler de coches', 'Comidas y cenas', 'Desayunos y cafés',
          'Entradas', 'Gasolina', 'Peajes', 'Trenes', 'Autobuses', 'Barcos y ferrys',
          'Aviones', 'Gastos personales', 'Supermercado', 'Farmacia', 'Parking',
          'Taxis', 'Transfer', 'Otros',
        ];
        const custom = data.custom_categories ?? [];
        const all = [...presets, ...custom.filter((c) => !presets.includes(c))];
        set({
          expenses: data.expenses,
          members: data.members,
          balances: data.balances,
          customCategories: custom,
          allCategories: all,
        });
      },

      setExpenses: (expenses) => set({ expenses }),

      patchExpenseCategory: (entryId, category) => {
        set((state) => ({
          expenses: state.expenses.map((e) =>
            e.entry_id === entryId ? { ...e, category } : e,
          ),
        }));
      },

      setSuggestions: (suggestions, newCats) => {
        set((state) => {
          const all = [...state.allCategories];
          for (const c of newCats) {
            if (!all.includes(c)) all.push(c);
          }
          return { suggestions, newCategoriesProposed: newCats, allCategories: all };
        });
      },

      applySuggestion: (entryId, category) => {
        set((state) => ({
          expenses: state.expenses.map((e) =>
            e.entry_id === entryId ? { ...e, category } : e,
          ),
          suggestions: state.suggestions.filter((s) => s.entry_id !== entryId),
        }));
      },

      applyAllSuggestions: (minConfidence = 0.85) => {
        const { suggestions, expenses } = get();
        const toApply = suggestions.filter((s) => s.confidence >= minConfidence);
        const applications = toApply.map((s) => ({
          entry_id: s.entry_id,
          category: s.suggested_category,
        }));
        set({
          expenses: expenses.map((e) => {
            const match = toApply.find((s) => s.entry_id === e.entry_id);
            return match ? { ...e, category: match.suggested_category } : e;
          }),
          suggestions: suggestions.filter((s) => s.confidence < minConfidence),
        });
        return applications;
      },

      addCustomCategory: (cat) => {
        set((state) => {
          if (state.allCategories.includes(cat)) return {};
          return {
            customCategories: [...state.customCategories, cat],
            allCategories: [...state.allCategories, cat],
          };
        });
      },

      setStep: (step) => set({ currentStep: step }),
      setLoadingAI: (v) => set({ isLoadingAI: v }),
      setError: (msg) => set({ error: msg }),
      setSettings: (s) => set({ settings: s }),
      setLastRegistryInput: (v) => set({ lastRegistryInput: v }),

      reset: () => set({
        sessionId: null,
        uploadSummary: null,
        expenses: [],
        allCategories: [],
        customCategories: [],
        members: [],
        balances: [],
        suggestions: [],
        newCategoriesProposed: [],
        currentStep: 'upload',
        isLoadingAI: false,
        error: null,
        // settings, lastRegistryInput intentionally NOT reset
      }),
    }),
    {
      name: 'easyexpense',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        // Provider settings + cached inputs
        settings: state.settings,
        lastRegistryInput: state.lastRegistryInput,
        // Full session state — survives page reloads
        sessionId: state.sessionId,
        uploadSummary: state.uploadSummary,
        currentStep: state.currentStep,
        expenses: state.expenses,
        members: state.members,
        balances: state.balances,
        allCategories: state.allCategories,
        customCategories: state.customCategories,
        suggestions: state.suggestions,
        newCategoriesProposed: state.newCategoriesProposed,
      }),
    },
  ),
);
