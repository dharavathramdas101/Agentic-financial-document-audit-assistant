"""
Parse a PDF into a flat list of Chunks with page/section/paragraph metadata.

Strategy:
  - Use PyMuPDF page.get_text("dict") to get block-level data including font sizes.
  - Blocks whose dominant font size exceeds the page median are treated as section headings.
  - Remaining text blocks are split by double-newline into paragraphs.
  - Each paragraph becomes one Chunk.
"""

import statistics
from pathlib import Path

import fitz  # PyMuPDF

from graph.state import Chunk


def parse_pdf(pdf_path: str, doc_id: str | None = None) -> list[Chunk]:
    """
    Args:
        pdf_path: Path to the PDF file.
        doc_id:   Identifier for this document. Defaults to the file stem.

    Returns:
        Ordered list of Chunks covering every paragraph in the PDF.
    """
    path = Path(pdf_path)
    if doc_id is None:
        doc_id = path.stem

    doc = fitz.open(str(path))
    chunks: list[Chunk] = []

    for page_num, page in enumerate(doc, start=1):
        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])

        # Collect all font sizes on the page to compute median
        all_sizes: list[float] = []
        for block in blocks:
            if block.get("type") != 0:  # type 0 = text
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sz = span.get("size", 0)
                    if sz > 0:
                        all_sizes.append(sz)

        median_size = statistics.median(all_sizes) if all_sizes else 12.0

        current_section = "unknown"
        paragraph_idx = 0

        for block in blocks:
            if block.get("type") != 0:
                continue

            # Concatenate all span text in this block
            block_text = " ".join(
                span["text"]
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            ).strip()

            if not block_text:
                continue

            # Dominant font size for this block
            block_sizes = [
                span.get("size", 0)
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if span.get("size", 0) > 0
            ]
            dominant_size = max(block_sizes) if block_sizes else 0

            # Heading heuristic: font clearly larger than body text
            if dominant_size > median_size * 1.15 and len(block_text) < 200:
                current_section = block_text
                continue

            # Split by double newline into paragraphs; fall back to whole block
            paragraphs = [p.strip() for p in block_text.split("\n\n") if p.strip()]
            if not paragraphs:
                paragraphs = [block_text]

            for para in paragraphs:
                if len(para) < 20:   # skip noise (page numbers, single words)
                    continue
                chunks.append(
                    Chunk(
                        text=para,
                        doc_id=doc_id,
                        page_num=page_num,
                        paragraph_idx=paragraph_idx,
                        section=current_section,
                    )
                )
                paragraph_idx += 1

    doc.close()
    return chunks
