from datetime import timezone

from backend.models import ParsedData, Expense, Allocation, Member, Balance, PRESET_CATEGORIES

# Map Tricount/bunq category enum strings → our preset category names.
# Tricount uses UPPER_SNAKE_CASE internally; values that don't appear here
# are treated as custom categories and added to custom_categories.
_TRICOUNT_CATEGORY_MAP: dict[str, str] = {
    # Confirmed from live API
    "FOOD_AND_DRINK":       "Comidas y cenas",
    # Accommodation — bunq's API enum confusingly calls this bucket "TRAVEL"
    # (verified against live data: every TRAVEL-category entry was lodging —
    # "Alojamiento X", "Guesthouse Y", "Accommodation Fee Z", etc.)
    "ACCOMMODATION":        "Estancias",
    "HOTEL":                "Estancias",
    "TRAVEL":               "Estancias",
    # Transport — specific
    "CAR_RENTAL":           "Alquiler de coches",
    "FUEL":                 "Gasolina",
    "GAS":                  "Gasolina",
    "TOLL":                 "Peajes",
    "TRAIN":                "Trenes",
    "BUS":                  "Autobuses",
    "BOAT":                 "Barcos y ferrys",
    "FERRY":                "Barcos y ferrys",
    "FLIGHT":               "Aviones",
    "TAXI":                 "Taxis",
    "RIDESHARE":            "Taxis",
    "PARKING":              "Parking",
    # Transport — generic (bunq uses TRANSPORTATION as a catch-all)
    "TRANSPORTATION":       "Taxis",
    # Leisure / activities
    "ENTERTAINMENT":        "Entradas",
    "ACTIVITIES":           "Entradas",
    "SPORT":                "Entradas",
    "SPORT_AND_FITNESS":    "Entradas",
    # Shopping / daily
    "GROCERIES":            "Supermercado",
    "SUPERMARKET":          "Supermercado",
    "SHOPPING":             "Supermercado",
    # Health
    "HEALTH":               "Farmacia",
    "PHARMACY":             "Farmacia",
    "MEDICAL":              "Farmacia",
    "HEALTH_AND_BEAUTY":    "Farmacia",
    # Personal
    "PERSONAL":             "Gastos personales",
    "PERSONAL_CARE":        "Gastos personales",
    # Settlements / reimbursements
    "SETTLEMENT":           "Transfer",
    # Generic fallback
    "OTHER":                "Otros",
    "UNCATEGORIZED":        "UNCATEGORIZED",
}


def _map_tricount_category(raw: str) -> str:
    """
    Convert a Tricount category string to one of our preset categories.
    - Known mappings → preset name
    - Unknown non-empty strings → kept as-is (becomes a custom category)
    - Empty / None → UNCATEGORIZED
    """
    if not raw:
        return "UNCATEGORIZED"
    mapped = _TRICOUNT_CATEGORY_MAP.get(raw.upper())
    if mapped is not None:
        return mapped
    # Unknown Tricount category: title-case it and pass through as custom
    return raw.replace("_", " ").title()


def _resolve_category(entry) -> str:
    """
    Decide an entry's category, in priority order:
    1. Balance/settlement entries (internal transfers between members, not real
       spending) always go to "Transfer", regardless of whatever category the
       Tricount API reports for them (usually UNCATEGORIZED).
    2. A member-defined custom category in the native Tricount app
       (`category_custom`, e.g. "Comidas & Cenas 🍜") is used as-is — these are
       real user-chosen labels and take priority over the coarse system enum.
    3. Otherwise, fall back to mapping Tricount's coarse `category` enum.
    """
    if entry.is_reimbursement:
        return "Transfer"
    custom = (entry.category_custom or "").strip()
    if custom:
        return custom
    return _map_tricount_category(entry.category)


def fetch_from_tricount(registry_id: str) -> ParsedData:
    """
    Fetch live data from Tricount API using tricount-extractor.
    Runs synchronously — wrap in run_in_executor for async FastAPI routes.
    No credentials needed: library auto-generates RSA session keys.
    """
    from tricount_extractor.client.client import TricountClient
    from tricount_extractor.models.registry import Registry

    with TricountClient() as client:
        response = client.get_registry(registry_id)
    registry = Registry.from_json(response.json())
    return _registry_to_parsed_data(registry)


def _registry_to_parsed_data(registry) -> ParsedData:
    expenses: list[Expense] = []
    allocations: list[Allocation] = []
    custom_categories: list[str] = []

    for entry in registry.entries:
        date = entry.date
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)

        category = _resolve_category(entry)

        # Collect unknown categories (not preset, not UNCATEGORIZED) as custom
        if category not in PRESET_CATEGORIES and category != "UNCATEGORIZED":
            if category not in custom_categories:
                custom_categories.append(category)

        expenses.append(Expense(
            entry_id=entry.id,
            date=date,
            description=entry.description,
            amount=abs(entry.amount.value),
            currency=entry.amount.currency,
            payer=entry.payer_name,
            is_reimbursement=entry.is_reimbursement,
            category=category,
        ))
        for alloc in entry.allocations:
            allocations.append(Allocation(
                entry_id=entry.id,
                participant=alloc.member_name,
                share=abs(alloc.amount.value),
                currency=alloc.amount.currency,
            ))

    members = [
        Member(
            member_id=m.id,
            member_name=m.display_name,
            status=m.status,
        )
        for m in registry.members
    ]

    balance_map: dict[str, float] = {m.display_name: 0.0 for m in registry.members}
    for entry in registry.entries:
        balance_map[entry.payer_name] = balance_map.get(entry.payer_name, 0.0) + abs(entry.amount.value)
        for alloc in entry.allocations:
            balance_map[alloc.member_name] = balance_map.get(alloc.member_name, 0.0) - abs(alloc.amount.value)

    balances = [
        Balance(member=name, balance=round(bal, 2))
        for name, bal in sorted(balance_map.items(), key=lambda x: -x[1])
    ]

    return ParsedData(
        expenses=expenses,
        allocations=allocations,
        members=members,
        balances=balances,
        custom_categories=custom_categories,
    )
