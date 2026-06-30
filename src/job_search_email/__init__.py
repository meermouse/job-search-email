"""Job search email plan package."""

from dotenv import load_dotenv

# Load local development secrets from a .env file (if present) before any
# submodule constructs an API client. No-op in CI, where the environment is
# populated directly (e.g. GitHub Actions secrets).
load_dotenv()

from .main import main  # noqa: E402  (must follow load_dotenv)

__all__ = ["main"]
