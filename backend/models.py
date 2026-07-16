from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel


PRESET_CATEGORIES: list[str] = [
    "Estancias",
    "Alquiler de coches",
    "Comidas y cenas",
    "Desayunos y cafés",
    "Entradas",
    "Gasolina",
    "Peajes",
    "Trenes",
    "Autobuses",
    "Barcos y ferrys",
    "Aviones",
    "Gastos personales",
    "Supermercado",
    "Farmacia",
    "Parking",
    "Taxis",
    "Transfer",
    "Otros",
]


class Expense(BaseModel):
    entry_id: int
    date: datetime
    description: str
    amount: float
    currency: str
    payer: str
    is_reimbursement: bool
    category: str


class Allocation(BaseModel):
    entry_id: int
    participant: str
    share: float
    currency: str


class Member(BaseModel):
    member_id: int
    member_name: str
    status: str


class Balance(BaseModel):
    member: str
    balance: float


class ParsedData(BaseModel):
    expenses: list[Expense]
    allocations: list[Allocation]
    members: list[Member]
    balances: list[Balance]
    custom_categories: list[str] = []


class AIProvider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    OLLAMA = "ollama"


class ProviderSettings(BaseModel):
    provider: AIProvider = AIProvider.OLLAMA
    claude_api_key: str = ""
    openai_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    openai_model: str = "gpt-4o-mini"
    ollama_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"


class CategorySuggestion(BaseModel):
    entry_id: int
    suggested_category: str
    confidence: float
    reasoning: str
    is_new_category: bool = False


class CategorizationResponse(BaseModel):
    suggestions: list[CategorySuggestion]
    new_categories_proposed: list[str]


class CategorizationRequest(BaseModel):
    session_id: str
    entry_ids: list[int] | None = None


class ApplyCategorizationRequest(BaseModel):
    session_id: str
    applications: list[dict]  # [{"entry_id": int, "category": str}]


class PatchExpenseRequest(BaseModel):
    category: str


class ReportRequest(BaseModel):
    session_id: str
    trip_name: str = "Trip Report"
    formats: list[str] = ["markdown", "pdf"]
    report_mode: str = "global"  # "global" or "personal"
    personal_member: str | None = None
    exclude_personal_expenses: bool = False
    exclude_categories: list[str] = []


class ReportResponse(BaseModel):
    markdown: str | None = None
    pdf_base64: str | None = None
    xlsx_base64: str | None = None
    csv_b64: str | None = None


class UploadSummary(BaseModel):
    session_id: str
    expense_count: int
    member_count: int
    date_from: str
    date_to: str
    total_amount: float
    currency: str


class FetchRequest(BaseModel):
    registry_id: str
