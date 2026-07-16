import base64
import logging
import re
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from typing import Optional

from backend.models import ReportRequest, ReportResponse
from backend.services.report_generator import generate_markdown, generate_pdf, generate_xlsx, generate_csv
from backend.services.html_report import generate_html_report
from backend.storage import session_store
from backend.limiter import limiter

logger = logging.getLogger("easyexpense.report")
router = APIRouter()


def _safe_filename(name: str) -> str:
    """Remove path separators, control characters, and shell-unsafe chars from a filename."""
    # Strip null bytes and all control characters (includes \n \r \t etc.)
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)
    # Remove path separators
    name = name.replace("/", "_").replace("\\", "_")
    # Remove Windows-forbidden and shell-special characters
    name = re.sub(r'[<>:"|?*`\';&$!]', "_", name)
    return name.strip()[:100] or "Trip_Report"


@router.post("/report", response_model=ReportResponse)
@limiter.limit("10/minute")
async def generate_report(request: Request, body: ReportRequest):
    data = session_store.get_session(body.session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Sanitize trip_name before passing to generators
    safe_trip_name = _safe_filename(body.trip_name)

    kwargs = dict(
        report_mode=body.report_mode,
        personal_member=body.personal_member,
        exclude_personal_expenses=body.exclude_personal_expenses,
        exclude_categories=body.exclude_categories,
    )

    result = ReportResponse()

    if "markdown" in body.formats:
        try:
            result.markdown = generate_markdown(data, safe_trip_name, **kwargs)
        except Exception:
            logger.exception("Markdown generation failed")
            raise HTTPException(status_code=500, detail="Report generation failed. Please try again.")

    if "pdf" in body.formats:
        try:
            pdf_bytes = generate_pdf(data, safe_trip_name, **kwargs)
            result.pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
        except Exception:
            logger.exception("PDF generation failed")
            raise HTTPException(status_code=500, detail="PDF generation failed. Please try again.")

    if "xlsx" in body.formats:
        try:
            xlsx_bytes = generate_xlsx(data, safe_trip_name, **kwargs)
            result.xlsx_base64 = base64.b64encode(xlsx_bytes).decode("utf-8")
        except Exception:
            logger.exception("XLSX generation failed")
            raise HTTPException(status_code=500, detail="XLSX generation failed. Please try again.")

    if "csv" in body.formats:
        try:
            csv_bytes = generate_csv(data, safe_trip_name, **kwargs)
            result.csv_b64 = base64.b64encode(csv_bytes).decode("utf-8")
        except Exception:
            logger.exception("CSV generation failed")
            raise HTTPException(status_code=500, detail="CSV generation failed. Please try again.")

    if "html" in body.formats:
        try:
            result.html = generate_html_report(data, safe_trip_name, **kwargs)
        except Exception:
            logger.exception("HTML chart generation failed")
            raise HTTPException(status_code=500, detail="Chart generation failed. Please try again.")

    return result


@router.get("/report/download/{session_id}/{format}")
@limiter.limit("10/minute")
async def download_report(
    request: Request,
    session_id: str, format: str, trip_name: str = "Trip Report",
    report_mode: str = "global", personal_member: Optional[str] = None,
    exclude_personal_expenses: bool = False,
    exclude_categories: list[str] = Query(default=[]),
):
    data = session_store.get_session(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")

    kwargs = dict(
        report_mode=report_mode,
        personal_member=personal_member,
        exclude_personal_expenses=exclude_personal_expenses,
        exclude_categories=exclude_categories,
    )

    safe_name = _safe_filename(trip_name)
    if format == "md":
        content = generate_markdown(data, safe_name, **kwargs)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.md"'},
        )
    elif format == "pdf":
        pdf_bytes = generate_pdf(data, safe_name, **kwargs)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
        )
    elif format == "xlsx":
        xlsx_bytes = generate_xlsx(data, safe_name, **kwargs)
        return Response(
            content=xlsx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.xlsx"'},
        )
    elif format == "csv":
        csv_bytes = generate_csv(data, safe_name, **kwargs)
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
        )
    elif format == "html":
        html_content = generate_html_report(data, safe_name, **kwargs)
        return Response(
            content=html_content.encode("utf-8"),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.html"'},
        )
    else:
        raise HTTPException(status_code=400, detail="Format must be 'md', 'pdf', 'xlsx', 'csv', or 'html'")
