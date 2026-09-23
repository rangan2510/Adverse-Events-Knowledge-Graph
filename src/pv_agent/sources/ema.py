"""EMA: the EU medicines list and SmPC sections.

EMA has no JSON API for product information. It publishes one spreadsheet of every centrally
authorised medicine (INN, ATC, authorisation status, EPAR URL) and the SmPC as a PDF at a fixed
URL. The spreadsheet is downloaded once per process; SmPC PDFs are fetched on demand and their
numbered sections extracted by regex.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from functools import lru_cache

import openpyxl
from pypdf import PdfReader

from pv_agent.sources.http import NotFound, get_bytes

LIST_URL = (
    "https://www.ema.europa.eu/system/files/documents/other/medicines_output_european_public_assessment_reports_en.xlsx"
)

# SmPC section headings, as the first word only: pypdf can break a heading mid-word
# ("Undesirable effect\ns"), so matching the full title fails.
SECTIONS = {
    "4.2": ("Posology", "4.3"),
    "4.3": ("Contraindications", "4.4"),
    "4.4": ("Special", "4.5"),
    "4.5": ("Interaction", "4.6"),
    "4.8": ("Undesirable", "4.9"),
    "5.2": ("Pharmacokinetic", "5.3"),
}


@dataclass
class Product:
    name: str
    inn: str
    status: str
    atc: str
    generic: bool
    epar_url: str

    @property
    def smpc_url(self) -> str:
        slug = self.epar_url.rstrip("/").rsplit("/", 1)[-1]
        return f"https://www.ema.europa.eu/en/documents/product-information/{slug}-epar-product-information_en.pdf"


@lru_cache(maxsize=1)
def _products() -> list[Product]:
    raw = get_bytes(LIST_URL, timeout=90)
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = None
    out: list[Product] = []
    for row in rows:
        if header is None:
            if row and row[0] == "Category":
                header = {str(h): i for i, h in enumerate(row) if h}
            continue
        if not row or row[header["Category"]] != "Human":
            continue
        out.append(_product(row, header))
    return out


def _product(row: tuple, header: dict[str, int]) -> Product:
    def cell(name: str) -> str:
        i = header.get(name)
        return str(row[i] or "").strip() if i is not None else ""

    return Product(
        name=cell("Medicine name"),
        inn=cell("International non-proprietary name (INN) / common name"),
        status=cell("Authorisation status"),
        atc=cell("ATC code"),
        generic=cell("Generic").lower() == "yes",
        epar_url=cell("URL"),
    )


def find(*names: str) -> list[Product]:
    """Authorised products whose INN or name matches any of the given spellings."""
    wanted = {n.lower().strip() for n in names if n}
    hits = []
    for p in _products():
        inn = p.inn.lower()
        if p.status.lower() != "authorised":
            continue
        if any(w in inn or w in p.name.lower() for w in wanted):
            hits.append(p)
    # Originators first, then generics; keeps the reference SmPC at the top.
    hits.sort(key=lambda p: (p.generic, p.name))
    return hits


@dataclass
class Smpc:
    product: Product
    sections: dict[str, str] = field(default_factory=dict)
    pages: int = 0


def _smpc_text(pdf: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(pdf))
    pages = []
    for i, page in enumerate(reader.pages):
        t = page.extract_text() or ""
        # Annex I is the SmPC; stop when Annex II (manufacturing) begins.
        if i > 3 and re.search(r"^\s*ANNEX II", t, re.M):
            break
        pages.append(t)
    return "\n".join(pages), len(pages)


def smpc(product: Product, wanted: tuple[str, ...] = ("4.5", "4.8")) -> Smpc:
    """Fetch the SmPC PDF and pull out the requested numbered sections."""
    try:
        pdf = get_bytes(product.smpc_url, timeout=120)
    except NotFound:
        return Smpc(product)
    text, pages = _smpc_text(pdf)
    out = Smpc(product, pages=pages)
    for num in wanted:
        title, nxt = SECTIONS[num]
        # The number and title may sit on separate lines in the PDF text.
        start = re.search(rf"\n\s*{re.escape(num)}\s+{title}", text)
        end = re.search(rf"\n\s*{re.escape(nxt)}\s+\S", text[start.end() :]) if start else None
        if start and end:
            body = text[start.start() : start.end() + end.start()]
            # pypdf breaks "ff" ligatures with stray spaces: "eff ects", "dif f erent". Two passes
            # because the second form has two gaps.
            for _ in range(2):
                body = re.sub(r"\b(\w*f) (f?\w+)\b", r"\1\2", body)
            out.sections[num] = " ".join(body.split())
    return out
