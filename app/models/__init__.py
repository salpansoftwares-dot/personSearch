# Re-export all models so Alembic's env.py can import them via one import.
from app.models.claim import Claim  # noqa: F401
from app.models.governance import Dispute, MergeLog, Query, Suppression  # noqa: F401
from app.models.person import Person, PersonClaim, PersonName  # noqa: F401
from app.models.saved_search import SavedSearch  # noqa: F401
from app.models.source import Source  # noqa: F401
