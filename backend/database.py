import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://enterprise_user:enterprise_password@127.0.0.1:5434/enterprise_rag"
)

connect_timeout = int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "5") or "5")
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": max(1, min(connect_timeout, 30))},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
