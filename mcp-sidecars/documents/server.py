"""MCP Documents sidecar — read and create PDF, Excel, and Word files."""

import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

server = create_mcp_server(
    "mcp-documents",
    "Read and create PDF, Excel (.xlsx), and Word (.docx) documents.",
)

WORK_DIR = os.environ.get("MCP_WORK_DIR", tempfile.gettempdir())
MAX_TEXT_CHARS = 16000


@server.tool()
def read_pdf(file_path: str) -> str:
    """Extract text content from a PDF file."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"--- Page {i + 1} ---\n{text}")
        return "\n".join(pages)[:MAX_TEXT_CHARS] if pages else "(no text found in PDF)"
    except ImportError:
        return "ERROR: pypdf not installed"
    except Exception as e:
        return f"ERROR: Failed to read PDF: {e}"


@server.tool()
def read_xlsx(file_path: str, sheet_name: str = "") -> str:
    """Read an Excel file and return contents as text. Optionally specify sheet_name."""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(file_path, read_only=True, data_only=True)
        sheets = [sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.sheetnames
        lines = []
        for sn in sheets:
            ws = wb[sn]
            lines.append(f"=== Sheet: {sn} ===")
            for row in ws.iter_rows(values_only=True):
                lines.append("\t".join(str(c) if c is not None else "" for c in row))
        wb.close()
        return "\n".join(lines)[:MAX_TEXT_CHARS]
    except ImportError:
        return "ERROR: openpyxl not installed"
    except Exception as e:
        return f"ERROR: Failed to read Excel file: {e}"


@server.tool()
def read_docx(file_path: str) -> str:
    """Extract text content from a Word (.docx) file."""
    try:
        from docx import Document
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)[:MAX_TEXT_CHARS] if paragraphs else "(no text found)"
    except ImportError:
        return "ERROR: python-docx not installed"
    except Exception as e:
        return f"ERROR: Failed to read docx: {e}"


@server.tool()
def create_pdf(text: str, output_filename: str = "output.pdf") -> str:
    """Create a simple PDF from text content. Returns the file path."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        path = os.path.join(WORK_DIR, output_filename)
        c = canvas.Canvas(path, pagesize=A4)
        width, height = A4
        y = height - 50
        for line in text.split("\n"):
            if y < 50:
                c.showPage()
                y = height - 50
            c.drawString(50, y, line[:100])
            y -= 14
        c.save()
        return f"PDF created: {path}"
    except ImportError:
        return "ERROR: reportlab not installed"
    except Exception as e:
        return f"ERROR: Failed to create PDF: {e}"


if __name__ == "__main__":
    run_server(server)
