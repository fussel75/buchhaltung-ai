from dataclasses import dataclass

from app.services.storage import resolve_stored_document_path


class PreviewError(ValueError):
    pass


MAX_PREVIEW_EDGE_PIXELS = 2600


@dataclass(frozen=True)
class PdfPreviewPage:
    page_count: int
    page_number: int
    png_bytes: bytes


def pdf_page_count(storage_path: str) -> int:
    try:
        import fitz
    except ImportError as exc:
        raise PreviewError("PDF-Vorschau ist serverseitig nicht verfügbar.") from exc

    path = resolve_stored_document_path(storage_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    with fitz.open(path) as pdf:
        return pdf.page_count


def render_pdf_preview_page(storage_path: str, page_number: int, zoom: float = 3.0) -> PdfPreviewPage:
    try:
        import fitz
    except ImportError as exc:
        raise PreviewError("PDF-Vorschau ist serverseitig nicht verfügbar.") from exc

    path = resolve_stored_document_path(storage_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    with fitz.open(path) as pdf:
        page_count = pdf.page_count
        if page_count < 1:
            raise PreviewError("PDF enthält keine Seiten.")
        if page_number < 1 or page_number > page_count:
            raise PreviewError("PDF-Seite existiert nicht.")

        page = pdf.load_page(page_number - 1)
        effective_zoom = _safe_zoom(page.rect.width, page.rect.height, zoom)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(effective_zoom, effective_zoom), alpha=False)
        return PdfPreviewPage(
            page_count=page_count,
            page_number=page_number,
            png_bytes=pixmap.tobytes("png"),
        )


def _safe_zoom(width: float, height: float, requested_zoom: float) -> float:
    longest_edge = max(width, height, 1)
    max_zoom = MAX_PREVIEW_EDGE_PIXELS / longest_edge
    return max(0.1, min(requested_zoom, max_zoom))
