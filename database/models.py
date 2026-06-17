from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ReviewQueue(Base):
    """
    Stores claims that failed the confidence gate or were flagged by the
    cross-verifier. A human reviewer approves or rejects each item before
    it feeds back into the final memo.
    """
    __tablename__ = "review_queue"

    id:            Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id:    Mapped[str]   = mapped_column(String(64),  nullable=False)
    claim:         Mapped[str]   = mapped_column(Text,        nullable=False)
    source_doc:    Mapped[str]   = mapped_column(String(255), nullable=False)
    source_page:   Mapped[int]   = mapped_column(Integer,     nullable=False)
    paragraph:     Mapped[int]   = mapped_column(Integer,     nullable=False, default=0)
    confidence:    Mapped[float] = mapped_column(Float,       nullable=False)
    flag_reason:   Mapped[str]   = mapped_column(String(50),  nullable=False)
    # "low_confidence" | "inconsistency_flagged" | "both"
    status:        Mapped[str]   = mapped_column(String(20),  nullable=False, default="pending")
    # "pending" | "approved" | "rejected"
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, server_default=func.now())
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, server_default=func.now(),
                                                      onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "session_id":    self.session_id,
            "claim":         self.claim,
            "source_doc":    self.source_doc,
            "source_page":   self.source_page,
            "paragraph":     self.paragraph,
            "confidence":    self.confidence,
            "flag_reason":   self.flag_reason,
            "status":        self.status,
            "reviewer_note": self.reviewer_note,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
        }


class FinancialRecord(Base):
    """
    One numeric data point extracted from a financial table in a PDF.

    Each row in a financial statement becomes N records — one per year column.
    Example: "Net revenue | 383,285 | 394,328 | 365,817" → 3 records (2023/22/21).

    Lookup path in cross-verifier:
      SELECT value FROM financial_records
      WHERE doc_id=? AND year=? AND line_item LIKE '%net revenue%'
    """
    __tablename__ = "financial_records"

    id:          Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id:      Mapped[str]   = mapped_column(String(255), nullable=False)
    line_item:   Mapped[str]   = mapped_column(String(512), nullable=False)
    line_item_normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    value:       Mapped[float] = mapped_column(Float,       nullable=False)
    unit:        Mapped[str]   = mapped_column(String(50),  nullable=False, default="millions")
    year:        Mapped[int]   = mapped_column(Integer,     nullable=False)
    source_page: Mapped[int]   = mapped_column(Integer,     nullable=False)
    table_type:  Mapped[str]   = mapped_column(String(50),  nullable=False, default="unknown")

    __table_args__ = (
        Index("ix_fr_doc_year_item", "doc_id", "year", "line_item_normalized"),
    )

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "doc_id":      self.doc_id,
            "line_item":   self.line_item,
            "value":       self.value,
            "unit":        self.unit,
            "year":        self.year,
            "source_page": self.source_page,
            "table_type":  self.table_type,
        }
