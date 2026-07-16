import json
import re
from backend.models import CategorySuggestion, PRESET_CATEGORIES

_CATEGORY_DESCRIPTIONS = {
    "Estancias": "accommodation: hotels, apartments, hostels, Airbnb, rental lodging",
    "Alquiler de coches": "car rental: vehicles, car hire",
    "Comidas y cenas": "restaurants, dinners, lunches, tavernas, eateries",
    "Desayunos y cafés": "breakfast, coffee shops, bakeries, cafes, pastries",
    "Entradas": "entrance fees, museums, attractions, tours, tickets, excursions",
    "Gasolina": "fuel, petrol, gas stations",
    "Peajes": "tolls, highway fees, road taxes",
    "Trenes": "trains, rail transport",
    "Autobuses": "buses, metro, trams, local transit",
    "Barcos y ferrys": "ferries, boats, island crossings, water transport",
    "Aviones": "flights, airport fees, plane tickets",
    "Gastos personales": "personal items, souvenirs, clothing, individual purchases",
    "Supermercado": "supermarket, grocery stores, convenience stores",
    "Farmacia": "pharmacy, medicine, health products",
    "Parking": "parking lots, parking meters, car parks",
    "Taxis": "taxis, ride-hailing (Uber, Cabify, Bolt), cab services, transfers",
    "Transfer": "final settlement transactions, reimbursements, balance closing transfers between participants",
    "Otros": "other or cannot determine from description",
}


def build_prompt(
    expenses: list[dict],
    available_categories: list[str],
    trip_context: str,
) -> tuple[str, str]:
    cat_lines = "\n".join(
        f"- {cat}: {_CATEGORY_DESCRIPTIONS.get(cat, cat)}"
        for cat in available_categories
    )

    system_prompt = f"""You are a travel expense categorizer. Your task is to assign each expense to exactly one category.

Available categories:
{cat_lines}

Rules:
1. Use the EXACT category name as listed above.
2. If an expense clearly belongs to a new category not listed (e.g. "Actividades deportivas"), you MAY propose it. Set "is_new_category": true and use your new name.
3. Respond ONLY with valid JSON matching the schema below — no explanation text, no markdown, no code blocks.
4. Confidence: 0.9+ for obvious matches, 0.6-0.9 for reasonable guesses, below 0.6 for uncertain.

Response JSON schema:
{{
  "categorizations": [
    {{
      "entry_id": <integer>,
      "category": "<category name>",
      "confidence": <float 0.0-1.0>,
      "reasoning": "<brief reason>",
      "is_new_category": <boolean>
    }}
  ],
  "new_categories_proposed": ["<category name>", ...]
}}"""

    user_prompt = f"""Trip context: {trip_context}

Categorize these expenses:
{json.dumps(expenses, ensure_ascii=False, indent=2)}"""

    return system_prompt, user_prompt


def parse_response(
    raw: str,
    expenses: list[dict],
) -> tuple[list[CategorySuggestion], list[str]]:
    entry_ids = [e["entry_id"] for e in expenses]

    # Try to extract JSON from response (handles markdown code blocks or extra text)
    json_str = _extract_json(raw)
    if json_str is None:
        return _fallback(entry_ids), []

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return _fallback(entry_ids), []

    categorizations = data.get("categorizations", [])
    new_cats = data.get("new_categories_proposed", [])

    # Build a lookup by entry_id
    result_map: dict[int, CategorySuggestion] = {}
    for item in categorizations:
        try:
            eid = int(item["entry_id"])
            suggestion = CategorySuggestion(
                entry_id=eid,
                suggested_category=str(item.get("category", "Otros")),
                confidence=float(item.get("confidence", 0.5)),
                reasoning=str(item.get("reasoning", "")),
                is_new_category=bool(item.get("is_new_category", False)),
            )
            result_map[eid] = suggestion
        except (KeyError, ValueError, TypeError):
            continue

    # Ensure every input expense has a suggestion
    suggestions = []
    for eid in entry_ids:
        if eid in result_map:
            suggestions.append(result_map[eid])
        else:
            suggestions.append(CategorySuggestion(
                entry_id=eid,
                suggested_category="Otros",
                confidence=0.1,
                reasoning="Not returned by AI",
                is_new_category=False,
            ))

    return suggestions, [str(c) for c in new_cats if c]


def _extract_json(text: str) -> str | None:
    text = text.strip()
    # Strip markdown code blocks
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # If it starts with {, try directly
    if text.startswith("{"):
        return text

    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return None


def _fallback(entry_ids: list[int]) -> list[CategorySuggestion]:
    return [
        CategorySuggestion(
            entry_id=eid,
            suggested_category="UNCATEGORIZED",
            confidence=0.0,
            reasoning="AI response could not be parsed",
            is_new_category=False,
        )
        for eid in entry_ids
    ]
