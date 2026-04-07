import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), nullable=False, unique=True)
    password = Column(Text, nullable=False)
    role = Column(String(50), nullable=False) # 'Guest' | 'Employee' | 'Admin'
    name = Column(String(255), nullable=False)
    created_at = Column("created_at", DateTime, default=datetime.utcnow, nullable=False)

    sessions = relationship("Session", back_populates="user")

class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(Text, nullable=False)
    created_at = Column("created_at", DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column("session_id", UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    role = Column(String(50), nullable=False) # 'user' | 'agent'
    content = Column(Text, nullable=False)
    created_at = Column("created_at", DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("Session", back_populates="messages")

class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_job_id = Column("parent_job_id", UUID(as_uuid=True), ForeignKey("ingest_jobs.id"), nullable=True)
    status = Column(String(32), nullable=False, default="queued")
    file_name = Column(String(512), nullable=False)
    file_path = Column(Text, nullable=False)
    role = Column(String(50), nullable=False, default="Employee")
    created_at = Column("created_at", DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column("started_at", DateTime, nullable=True)
    finished_at = Column("finished_at", DateTime, nullable=True)
    rolled_back_at = Column("rolled_back_at", DateTime, nullable=True)
    error = Column(Text, nullable=True)
    errors_json = Column("errors_json", Text, nullable=True)
    vector_ids_json = Column("vector_ids_json", Text, nullable=True)
    chunk_ids_json = Column("chunk_ids_json", Text, nullable=True)
    num_chunks_total = Column("num_chunks_total", Integer, nullable=True)
    num_chunks_success = Column("num_chunks_success", Integer, nullable=True)
    num_summary_docs = Column("num_summary_docs", Integer, nullable=True)
    num_chunk_docs = Column("num_chunk_docs", Integer, nullable=True)
    num_embeddings = Column("num_embeddings", Integer, nullable=True)
    embedding_model = Column("embedding_model", String(128), nullable=True)

    parent = relationship("IngestJob", remote_side=[id])
