from sqlalchemy import Column, DateTime, Integer, String, text

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    google_sub = Column(String, nullable=True, unique=True)
    status = Column(
        String,
        nullable=False,
        default="ACTIVE",
        server_default=text("'ACTIVE'"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
