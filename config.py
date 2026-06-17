from dotenv import load_dotenv
import os

load_dotenv()

GROQ_API_KEY: str = os.environ["GROQ_API_KEY"]
GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

LLM_MODEL: str  = os.getenv("LLM_MODEL",   "llama-3.3-70b-versatile")
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
CHROMA_PATH: str = os.getenv("CHROMA_PATH", "./chroma_db")

TOP_K_RETRIEVAL: int = 10
RRF_K: int = 60

# Human review queue
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.8"))

# Database URL — defaults to SQLite (file-based, zero config).
# Switch to PostgreSQL: set DATABASE_URL=postgresql+psycopg2://user:pass@host/db
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite:///./finaudit_review.db"
)
