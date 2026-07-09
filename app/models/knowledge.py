from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import UserDefinedType

Base = declarative_base()


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def get_col_spec(self, **kwargs):
        return f"vector({self.dimensions})"


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(BigInteger, primary_key=True)
    title = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=False)
    source_path = Column(Text, nullable=True)
    domain = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    chunks = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(BigInteger, primary_key=True)
    document_id = Column(
        BigInteger,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    document = relationship("KnowledgeDocument", back_populates="chunks")
