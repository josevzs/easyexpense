from __future__ import annotations
import unicodedata
from collections import defaultdict, Counter
from datetime import datetime
from io import BytesIO

from backend.models import ParsedData
from backend.services.currency import convert_to_eur


# ─────────────────────────────────────────────
#  Font setup
#
#  ReportLab's built-in Helvetica uses WinAnsiEncoding (Latin-1 only).
#  Greek characters sit at U+0391+ and are outside that range entirely.
#  We register Arial (metrically identical to Helvetica, ships on every
#  Windows install) as a Unicode TTF so Greek renders natively.
#  If no suitable TTF is found we fall back to the built-in Helvetica
#  and strip non-Latin-1 characters via _pdf_safe().
# ─────────────────────────────────────────────

_PDF_FONT = "Helvetica"
_PDF_FONT_BOLD = "Helvetica-Bold"
_PDF_UNICODE = False   # True once a Unicode TTF is registered


def _setup_pdf_fonts() -> None:
    """Register a Unicode TTF under the names PDF_FONT / PDF_FONT_BOLD.

    Called once at PDF generation time.  On Windows, Arial is always
    present and is metrically equivalent to Helvetica.
    """
    global _PDF_FONT, _PDF_FONT_BOLD, _PDF_UNICODE
    if _PDF_UNICODE:
        return

    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        # Windows — Arial (metrically identical to Helvetica)
        ("C:/Windows/Fonts/arial.ttf",   "C:/Windows/Fonts/arialbd.ttf"),
        # macOS — Arial
        ("/Library/Fonts/Arial.ttf",      "/Library/Fonts/Arial Bold.ttf"),
        # macOS — Helvetica Neue TTF (sometimes present)
        ("/Library/Fonts/Helvetica Neue.ttf", "/Library/Fonts/Helvetica Neue Bold.ttf"),
        # Linux — Noto Sans (wide Unicode coverage)
        ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
         "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
        # Linux — DejaVu Sans
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]

    for reg_path, bold_path in candidates:
        if not os.path.exists(reg_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("_TRRegular", reg_path))
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont("_TRBold", bold_path))
            else:
                pdfmetrics.registerFont(TTFont("_TRBold", reg_path))
            _PDF_FONT = "_TRRegular"
            _PDF_FONT_BOLD = "_TRBold"
            _PDF_UNICODE = True
            return
        except Exception:
            continue
    # No TTF found — fall back to built-in Helvetica with _pdf_safe() sanitising text


# ── Accented Greek → unaccented Greek ──
# (used only in the Latin-1 fallback path so Greek base letters stay Greek)
_GREEK_ACCENTED = str.maketrans(
    "ΆΈΉΊΌΎΏΪΫάέήίόύώϊϋΐΰ",
    "ΑΕΗΙΟΥΩΙΥαεηιουωιυιυ",
)
# Plain Greek → nearest Latin phonetic (last-resort fallback only)
_GREEK_TO_LATIN = str.maketrans(
    "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρσςτυφχψω",
    "ABGDEZETIKLMNXOPRSTYFXPOabgdezetiklmnxoprsst yfxpo".replace(" ", ""),
)


def _pdf_safe(text: str) -> str:
    """Sanitise text for Helvetica (Latin-1) when no Unicode TTF is available.

    1. Accented Greek → unaccented Greek base (ά→α keeps it Greek).
    2. Plain Greek → nearest Latin phonetic (Α→A, only if still unencodable).
    3. Accented Latin → base letter via NFD (é→e, ñ→n).
    4. Any remaining non-Latin-1 character → '?'.
    """
    if _PDF_UNICODE:
        return text  # TTF registered — no sanitisation needed

    text = text.translate(_GREEK_ACCENTED)
    text = text.translate(_GREEK_TO_LATIN)
    decomposed = unicodedata.normalize("NFD", text)
    out = []
    for ch in decomposed:
        if unicodedata.category(ch) == "Mn":
            continue
        try:
            ch.encode("latin-1")
            out.append(ch)
        except (UnicodeEncodeError, ValueError):
            out.append("?")
    return "".join(out)


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _fmt(amount: float) -> str:
    return f"{amount:,.2f} €"


def _category_totals(expenses) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for e in expenses:
        totals[e.category] += e.amount
    return dict(totals)


def _filter_expenses(
    data: ParsedData,
    report_mode: str,
    personal_member: str | None,
    exclude_personal_expenses: bool,
    exclude_categories: list[str] | None = None,
):
    """Return expense list with amounts adjusted for the report mode.

    In personal mode each expense's amount is replaced by the member's
    allocated share (from data.allocations) rather than the full expense
    total, so every figure in the report reflects what that person owes.
    """
    expenses = [e for e in data.expenses if not e.is_reimbursement]

    if exclude_categories:
        excluded = set(exclude_categories)
        expenses = [e for e in expenses if e.category not in excluded]

    if report_mode == "personal" and personal_member:
        all_expense_ids = {e.entry_id for e in expenses}

        # Build share lookup: entry_id → member's share amount
        share_map: dict[int, float] = {
            a.entry_id: a.share
            for a in data.allocations
            if a.participant == personal_member and a.entry_id in all_expense_ids
        }

        if exclude_personal_expenses:
            alloc_count = Counter(
                a.entry_id for a in data.allocations if a.entry_id in all_expense_ids
            )
            share_map = {eid: s for eid, s in share_map.items() if alloc_count[eid] > 1}

        # Keep only expenses this member participates in, with amount = their share
        expenses = [
            e.model_copy(update={"amount": share_map[e.entry_id]})
            for e in expenses
            if e.entry_id in share_map
        ]

    return expenses


def _personal_stats(data: ParsedData, personal_member: str) -> dict:
    """Compute global comparison stats for a member (using real allocation shares)."""
    all_expenses = [e for e in data.expenses if not e.is_reimbursement]
    all_ids = {e.entry_id for e in all_expenses}
    global_total = sum(e.amount for e in all_expenses)
    n_members = max(len(data.members), 1)
    global_per_person = global_total / n_members
    personal_paid = sum(e.amount for e in all_expenses if e.payer == personal_member)
    # Use actual allocation shares (not a naive split) for the member's real total
    personal_share = sum(
        a.share for a in data.allocations
        if a.participant == personal_member and a.entry_id in all_ids
    )
    return {
        "global_total": global_total,
        "global_per_person": global_per_person,
        "n_members": n_members,
        "personal_paid": personal_paid,
        "personal_share": personal_share,
        "diff_from_avg": personal_share - global_per_person,
    }


# ─────────────────────────────────────────────
#  Markdown
# ─────────────────────────────────────────────

def generate_markdown(
    data: ParsedData,
    trip_name: str,
    report_mode: str = "global",
    personal_member: str | None = None,
    exclude_personal_expenses: bool = False,
    exclude_categories: list[str] | None = None,
) -> str:
    data = convert_to_eur(data)
    expenses = _filter_expenses(data, report_mode, personal_member, exclude_personal_expenses, exclude_categories)
    dates = [e.date for e in expenses if e.date]
    date_from = min(dates).strftime("%d %b %Y") if dates else "?"
    date_to   = max(dates).strftime("%d %b %Y") if dates else "?"
    members_str = ", ".join(m.member_name for m in data.members)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = []
    lines.append(f"# {trip_name}")
    lines.append(f"**Generated:** {now}  ")
    lines.append(f"**Period:** {date_from} – {date_to}  ")
    if report_mode == "personal" and personal_member:
        lines.append(f"**Report for:** {personal_member}  ")
        if exclude_personal_expenses:
            lines.append(f"*Purely personal expenses excluded*  ")
    else:
        lines.append(f"**Participants:** {members_str}  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary by category
    lines.append("## Summary by Category")
    lines.append("")
    totals = _category_totals(expenses)
    grand_total = sum(totals.values())
    lines.append("| Category | Amount | % | # Items |")
    lines.append("|----------|--------|---|---------|")
    for cat, total in sorted(totals.items(), key=lambda x: -x[1]):
        pct = (total / grand_total * 100) if grand_total else 0
        count = sum(1 for e in expenses if e.category == cat)
        lines.append(f"| {cat} | {_fmt(total)} | {pct:.1f}% | {count} |")
    lines.append(f"| **TOTAL** | **{_fmt(grand_total)}** | **100%** | **{len(expenses)}** |")
    lines.append("")

    # Personal comparison block
    if report_mode == "personal" and personal_member:
        stats = _personal_stats(data, personal_member)
        diff = stats["diff_from_avg"]
        sign = "+" if diff >= 0 else ""
        lines.append("## Personal vs Global Comparison")
        lines.append("")
        lines.append("| Metric | Amount |")
        lines.append("|--------|--------|")
        lines.append(f"| Global trip total | {_fmt(stats['global_total'])} |")
        lines.append(f"| Fair share per person ({stats['n_members']} members) | {_fmt(stats['global_per_person'])} |")
        lines.append(f"| {personal_member} — total paid | {_fmt(stats['personal_paid'])} |")
        lines.append(f"| {personal_member} — allocated share | {_fmt(stats['personal_share'])} |")
        lines.append(f"| Difference from fair share | {sign}{_fmt(diff)} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Uncategorized warning
    uncategorized = [e for e in expenses if e.category == "UNCATEGORIZED"]
    if uncategorized:
        lines.append(f"> ⚠️ **{len(uncategorized)} expenses still uncategorized** — please review.")
        lines.append("")

    if report_mode == "global":
        lines.append("---")
        lines.append("")
        # Balance sheet
        lines.append("## Balance Sheet")
        lines.append("")
        paid_by: dict[str, float] = defaultdict(float)
        for e in expenses:
            paid_by[e.payer] += e.amount
        share_per = grand_total / len(data.members) if data.members else 0
        lines.append("| Participant | Paid | Fair Share | Balance |")
        lines.append("|-------------|------|------------|---------|")
        for b in data.balances:
            paid = paid_by.get(b.member, 0.0)
            balance_val = paid - share_per
            sign = "+" if balance_val >= 0 else ""
            lines.append(f"| {b.member} | {_fmt(paid)} | {_fmt(share_per)} | {sign}{_fmt(balance_val)} |")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Expenses by category
    lines.append("## Expenses by Category")
    lines.append("")
    by_cat: dict[str, list] = defaultdict(list)
    for e in expenses:
        by_cat[e.category].append(e)

    for cat in sorted(by_cat.keys()):
        cat_expenses = sorted(by_cat[cat], key=lambda e: e.date)
        subtotal = sum(e.amount for e in cat_expenses)
        lines.append(f"### {cat}")
        lines.append("")
        lines.append("| Date | Description | Paid by | Amount |")
        lines.append("|------|-------------|---------|--------|")
        for e in cat_expenses:
            d = e.date.strftime("%d %b") if e.date else "?"
            lines.append(f"| {d} | {e.description} | {e.payer} | {_fmt(e.amount)} |")
        lines.append(f"| | **Subtotal** | | **{_fmt(subtotal)}** |")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Chronological full list
    lines.append("## All Expenses (Chronological)")
    lines.append("")
    lines.append("| Date | Description | Category | Paid by | Amount |")
    lines.append("|------|-------------|----------|---------|--------|")
    for e in sorted(expenses, key=lambda e: e.date or datetime.min):
        d = e.date.strftime("%d %b %Y") if e.date else "?"
        lines.append(f"| {d} | {e.description} | {e.category} | {e.payer} | {_fmt(e.amount)} |")
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────
#  PDF  (ReportLab Platypus) — Helvetica throughout
# ─────────────────────────────────────────────

def generate_pdf(
    data: ParsedData,
    trip_name: str,
    report_mode: str = "global",
    personal_member: str | None = None,
    exclude_personal_expenses: bool = False,
    exclude_categories: list[str] | None = None,
) -> bytes:
    _setup_pdf_fonts()
    data = convert_to_eur(data)

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )

    S = _pdf_safe  # sanitise user strings when falling back to built-in Helvetica

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TRTitle", parent=styles["Title"],
        fontName=_PDF_FONT_BOLD, fontSize=20, spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        "TRH2", parent=styles["Heading2"],
        fontName=_PDF_FONT_BOLD, fontSize=14, spaceBefore=12, spaceAfter=6,
    )
    h3_style = ParagraphStyle(
        "TRH3", parent=styles["Heading3"],
        fontName=_PDF_FONT_BOLD, fontSize=11, spaceBefore=8, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "TRBody", parent=styles["Normal"],
        fontName=_PDF_FONT, fontSize=10,
    )

    expenses = _filter_expenses(data, report_mode, personal_member, exclude_personal_expenses, exclude_categories)
    dates = [e.date for e in expenses if e.date]
    date_from = min(dates).strftime("%d %b %Y") if dates else "?"
    date_to   = max(dates).strftime("%d %b %Y") if dates else "?"
    members_str = ", ".join(S(m.member_name) for m in data.members)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    totals = _category_totals(expenses)
    grand_total = sum(totals.values())

    story = []

    # ── Header ──
    story.append(Paragraph(S(trip_name), title_style))
    if report_mode == "personal" and personal_member:
        story.append(Paragraph(f"<b>Report for:</b> {S(personal_member)}", body_style))
        if exclude_personal_expenses:
            story.append(Paragraph("(Purely personal expenses excluded)", body_style))
    else:
        story.append(Paragraph(f"<b>Participants:</b> {members_str}", body_style))
    story.append(Paragraph(f"<b>Period:</b> {date_from} - {date_to}", body_style))
    story.append(Paragraph(f"<b>Generated:</b> {now}", body_style))
    story.append(Spacer(1, 0.5 * cm))

    # ── Summary table ──
    story.append(Paragraph("Summary by Category", h2_style))

    header = ["Category", "Amount (EUR)", "%", "# Items"]
    rows = [header]
    for cat, total in sorted(totals.items(), key=lambda x: -x[1]):
        pct = (total / grand_total * 100) if grand_total else 0
        count = sum(1 for e in expenses if e.category == cat)
        rows.append([S(cat), f"{total:,.2f}", f"{pct:.1f}%", str(count)])
    rows.append(["TOTAL", f"{grand_total:,.2f}", "100%", str(len(expenses))])

    col_widths = [9 * cm, 3.5 * cm, 2 * cm, 2 * cm]
    tbl = Table(rows, colWidths=col_widths)
    tbl.setStyle(_summary_table_style(len(rows)))
    story.append(tbl)
    story.append(Spacer(1, 0.5 * cm))

    # ── Personal comparison ──
    if report_mode == "personal" and personal_member:
        story.append(Paragraph("Personal vs Global Comparison", h2_style))
        stats = _personal_stats(data, personal_member)
        diff = stats["diff_from_avg"]
        sign = "+" if diff >= 0 else ""
        pm = S(personal_member)
        comp_rows = [
            ["Metric", "Amount (EUR)"],
            ["Global trip total", f"{stats['global_total']:,.2f}"],
            [f"Fair share per person ({stats['n_members']} members)", f"{stats['global_per_person']:,.2f}"],
            [f"{pm} - total paid", f"{stats['personal_paid']:,.2f}"],
            [f"{pm} - allocated share", f"{stats['personal_share']:,.2f}"],
            ["Difference from fair share", f"{sign}{abs(diff):,.2f}"],
        ]
        comp_tbl = Table(comp_rows, colWidths=[10 * cm, 3.5 * cm])
        comp_tbl.setStyle(_comparison_table_style(diff))
        story.append(comp_tbl)
        story.append(Spacer(1, 0.5 * cm))

    # ── Balance sheet (global only) ──
    if report_mode == "global":
        story.append(Paragraph("Balance Sheet", h2_style))
        paid_by: dict[str, float] = defaultdict(float)
        for e in expenses:
            paid_by[e.payer] += e.amount
        share_per = grand_total / len(data.members) if data.members else 0

        bal_header = ["Participant", "Paid (EUR)", "Fair Share (EUR)", "Balance (EUR)"]
        bal_rows = [bal_header]
        for b in data.balances:
            paid = paid_by.get(b.member, 0.0)
            bal = paid - share_per
            sign = "+" if bal >= 0 else ""
            bal_rows.append([S(b.member), f"{paid:,.2f}", f"{share_per:,.2f}", f"{sign}{bal:,.2f}"])

        bal_tbl = Table(bal_rows, colWidths=[5 * cm, 3.5 * cm, 4 * cm, 4 * cm])
        bal_tbl.setStyle(_balance_table_style(bal_rows))
        story.append(bal_tbl)

    story.append(PageBreak())

    # ── Per-category sections ──
    story.append(Paragraph("Expenses by Category", h2_style))

    by_cat: dict[str, list] = defaultdict(list)
    for e in expenses:
        by_cat[e.category].append(e)

    for cat in sorted(by_cat.keys()):
        cat_expenses = sorted(by_cat[cat], key=lambda e: e.date)
        subtotal = sum(e.amount for e in cat_expenses)
        story.append(Paragraph(S(cat), h3_style))

        cat_header = ["Date", "Description", "Paid by", "Amount (EUR)"]
        cat_rows = [cat_header]
        for e in cat_expenses:
            d = e.date.strftime("%d %b") if e.date else "?"
            cat_rows.append([d, S(_truncate(e.description, 40)), S(e.payer), f"{e.amount:,.2f}"])
        cat_rows.append(["", "Subtotal", "", f"{subtotal:,.2f}"])

        cat_tbl = Table(cat_rows, colWidths=[2.5 * cm, 8.5 * cm, 3 * cm, 2.5 * cm])
        cat_tbl.setStyle(_category_table_style(len(cat_rows)))
        story.append(cat_tbl)
        story.append(Spacer(1, 0.3 * cm))

    doc.build(story, onFirstPage=_footer_canvas, onLaterPages=_footer_canvas)
    return buffer.getvalue()


def _footer_canvas(canvas, doc):
    from reportlab.lib import colors as _colors
    from reportlab.lib.units import cm as _cm
    canvas.saveState()
    canvas.setFont(_PDF_FONT, 8)
    canvas.setFillColor(_colors.grey)
    canvas.drawRightString(
        doc.pagesize[0] - 2 * _cm,
        1.2 * _cm,
        f"Page {doc.page}",
    )
    canvas.restoreState()


def _summary_table_style(n_rows: int):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111111")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _PDF_FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), _PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("FONTNAME", (0, n_rows - 1), (-1, n_rows - 1), _PDF_FONT_BOLD),
        ("BACKGROUND", (0, n_rows - 1), (-1, n_rows - 1), colors.HexColor("#e8e8e8")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, n_rows - 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f5f5f5")))
    return TableStyle(style)


def _balance_table_style(rows: list):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111111")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _PDF_FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), _PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, row in enumerate(rows[1:], start=1):
        bal_str = row[-1]
        if bal_str.startswith("+") or (not bal_str.startswith("-") and float(bal_str.replace(",", "") or 0) > 0):
            style.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#1a7a3c")))
        elif bal_str.startswith("-"):
            style.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#c0392b")))
    return TableStyle(style)


def _comparison_table_style(diff: float):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle
    diff_color = colors.HexColor("#1a7a3c") if diff >= 0 else colors.HexColor("#c0392b")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111111")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _PDF_FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), _PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        # Last row is diff — colour it
        ("TEXTCOLOR", (1, -1), (1, -1), diff_color),
        ("FONTNAME", (0, -1), (-1, -1), _PDF_FONT_BOLD),
    ]
    for i in range(1, 6):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f5f5f5")))
    return TableStyle(style)


def _category_table_style(n_rows: int):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _PDF_FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), _PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ("FONTNAME", (0, n_rows - 1), (-1, n_rows - 1), _PDF_FONT_BOLD),
        ("BACKGROUND", (0, n_rows - 1), (-1, n_rows - 1), colors.HexColor("#e8e8e8")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(1, n_rows - 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f5f5f5")))
    return TableStyle(style)


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


# ─────────────────────────────────────────────
#  XLSX  (pandas + openpyxl)
# ─────────────────────────────────────────────

def generate_xlsx(
    data: ParsedData,
    trip_name: str,
    report_mode: str = "global",
    personal_member: str | None = None,
    exclude_personal_expenses: bool = False,
    exclude_categories: list[str] | None = None,
) -> bytes:
    import pandas as pd

    data = convert_to_eur(data)
    expenses = _filter_expenses(data, report_mode, personal_member, exclude_personal_expenses, exclude_categories)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        # ── Sheet 1: All expenses ──
        exp_rows = [
            {
                "Date": e.date.strftime("%Y-%m-%d") if e.date else "",
                "Description": e.description,
                "Category": e.category,
                "Paid by": e.payer,
                "Amount (EUR)": round(e.amount, 2),
            }
            for e in sorted(expenses, key=lambda e: e.date or datetime.min)
        ]
        pd.DataFrame(exp_rows).to_excel(writer, sheet_name="Expenses", index=False)

        # ── Sheet 2: Summary by category ──
        totals = _category_totals(expenses)
        grand_total = sum(totals.values())
        summary_rows = [
            {
                "Category": cat,
                "Amount (EUR)": round(total, 2),
                "% of Total": round(total / grand_total * 100, 1) if grand_total else 0.0,
                "# Items": sum(1 for e in expenses if e.category == cat),
            }
            for cat, total in sorted(totals.items(), key=lambda x: -x[1])
        ]
        summary_rows.append({
            "Category": "TOTAL",
            "Amount (EUR)": round(grand_total, 2),
            "% of Total": 100.0,
            "# Items": len(expenses),
        })
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

        # ── Sheet 3: Balance sheet (global) or Personal comparison (personal) ──
        if report_mode == "global":
            paid_by: dict[str, float] = defaultdict(float)
            for e in expenses:
                paid_by[e.payer] += e.amount
            share_per = grand_total / len(data.members) if data.members else 0.0
            balance_rows = [
                {
                    "Participant": b.member,
                    "Paid (EUR)": round(paid_by.get(b.member, 0.0), 2),
                    "Fair Share (EUR)": round(share_per, 2),
                    "Balance (EUR)": round(paid_by.get(b.member, 0.0) - share_per, 2),
                }
                for b in data.balances
            ]
            pd.DataFrame(balance_rows).to_excel(writer, sheet_name="Balance Sheet", index=False)
        elif report_mode == "personal" and personal_member:
            stats = _personal_stats(data, personal_member)
            comp_rows = [
                {"Metric": "Global trip total", "Amount (EUR)": round(stats["global_total"], 2)},
                {"Metric": f"Fair share per person ({stats['n_members']} members)", "Amount (EUR)": round(stats["global_per_person"], 2)},
                {"Metric": f"{personal_member} \u2014 total paid", "Amount (EUR)": round(stats["personal_paid"], 2)},
                {"Metric": f"{personal_member} \u2014 allocated share", "Amount (EUR)": round(stats["personal_share"], 2)},
                {"Metric": "Difference from fair share", "Amount (EUR)": round(stats["diff_from_avg"], 2)},
            ]
            pd.DataFrame(comp_rows).to_excel(writer, sheet_name="Personal Comparison", index=False)

    return buffer.getvalue()


# ─────────────────────────────────────────────
#  CSV  (pandas)
# ─────────────────────────────────────────────

def generate_csv(
    data: ParsedData,
    trip_name: str,
    report_mode: str = "global",
    personal_member: str | None = None,
    exclude_personal_expenses: bool = False,
    exclude_categories: list[str] | None = None,
) -> bytes:
    import pandas as pd

    data = convert_to_eur(data)
    expenses = _filter_expenses(data, report_mode, personal_member, exclude_personal_expenses, exclude_categories)

    rows = [
        {
            "Date": e.date.strftime("%Y-%m-%d") if e.date else "",
            "Description": e.description,
            "Category": e.category,
            "Paid by": e.payer,
            "Amount (EUR)": round(e.amount, 2),
        }
        for e in sorted(expenses, key=lambda e: e.date or datetime.min)
    ]

    buffer = BytesIO()
    # utf-8-sig BOM ensures Excel opens the file with correct encoding
    pd.DataFrame(rows).to_csv(buffer, index=False, encoding="utf-8-sig")
    return buffer.getvalue()
