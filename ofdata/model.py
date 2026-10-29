"""The only shape a fee record may take.

Every rule in this file exists to make one thing impossible: publishing a fee
that cannot be traced to an official source on a known date.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field, asdict

ISO = "%Y-%m-%d"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Anything not on an official/public-authority host must be justified explicitly.
OFFICIAL_TLDS = (".gov", ".gov.uk", ".gob.", ".govt.", ".mil", ".europa.eu", ".gc.ca", ".admin.ch")
STATUSES = ("verified", "draft", "stale")


class RecordError(ValueError):
    """Raised when a record would be dishonest to publish."""


def _parse_date(value, what):
    if isinstance(value, dt.date):
        return value
    try:
        return dt.datetime.strptime(str(value), ISO).date()
    except (TypeError, ValueError):
        raise RecordError(f"{what}: expected YYYY-MM-DD, got {value!r}") from None


def _is_official(url):
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    return host.endswith(OFFICIAL_TLDS) or host.endswith(".gov")


@dataclass
class FeeItem:
    """One priced line: a fee amount plus the currency it is charged in."""

    name: str
    amount: float
    currency: str
    notes: str = ""

    def __post_init__(self):
        if not self.name.strip():
            raise RecordError("fee item needs a name")
        if not isinstance(self.amount, (int, float)) or self.amount < 0:
            raise RecordError(f"{self.name}: amount must be a non-negative number")
        if not re.fullmatch(r"[A-Z]{3}", self.currency or ""):
            raise RecordError(f"{self.name}: currency must be an ISO-4217 code, got {self.currency!r}")


@dataclass
class FeeRecord:
    """A single fee fact about one country, with its proof attached."""

    country: str
    country_name: str
    slug: str
    category: str
    title: str
    fees: list = field(default_factory=list)
    source_url: str = ""
    source_name: str = ""
    source_type: str = "official"
    verified_on: str = ""
    status: str = "draft"
    checked_by: str = "human"
    review_required: bool = False
    # Regexes that must each still match the source page. A record with no
    # patterns is only checked for reachability; a record with patterns is
    # checked for the actual number, which is a much stronger promise.
    claim_patterns: list = field(default_factory=list)
    notes: str = ""
    extra_sources: list = field(default_factory=list)

    def __post_init__(self):
        if not re.fullmatch(r"[A-Z]{2}", self.country or ""):
            raise RecordError(f"country must be ISO-3166 alpha-2, got {self.country!r}")
        if not SLUG_RE.fullmatch(self.slug or ""):
            raise RecordError(f"slug must be lower-kebab-case, got {self.slug!r}")
        if not self.title.strip():
            raise RecordError("title is required")
        if not self.source_url:
            raise RecordError("source_url is required - an unsourced fee is a guess")
        if not str(self.source_url).startswith("https://"):
            raise RecordError(f"source_url must be https, got {self.source_url!r}")
        if self.status not in STATUSES:
            raise RecordError(f"status must be one of {STATUSES}, got {self.status!r}")
        if self.status != "draft":
            if not self.verified_on:
                raise RecordError("a published record needs verified_on")
            if self.checked_by not in ("human", "automated", "mixed"):
                raise RecordError(f"bad checked_by: {self.checked_by!r}")
        self.verified_on = str(self.verified_on or "")
        self.claim_patterns = [str(p) for p in (self.claim_patterns or [])]
        for pattern in self.claim_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise RecordError(f"claim_patterns: bad regex {pattern!r}: {exc}") from None
        self.fees = [f if isinstance(f, FeeItem) else FeeItem(**f) for f in self.fees]
        if not self.fees:
            raise RecordError("a record with no fee lines has nothing to show")

    # -- derived facts -----------------------------------------------------
    @property
    def verified_date(self):
        return _parse_date(self.verified_on, "verified_on") if self.verified_on else None

    def age_days(self, today=None):
        if not self.verified_date:
            return None
        return ((today or dt.date.today()) - self.verified_date).days

    def is_fresh(self, max_age_days=90, today=None):
        age = self.age_days(today)
        return age is not None and 0 <= age <= max_age_days

    def is_official_source(self):
        return _is_official(self.source_url)

    def effective_status(self, max_age_days=90, today=None):
        """What the site is allowed to claim, regardless of what the file says."""
        if self.status == "draft":
            return "draft"
        # A source that changed under us may now say something else, so the old
        # number is no longer something we can vouch for. Hide it until a person
        # re-reads the page, rather than refreshing the date and implying we did.
        if self.review_required:
            return "review"
        return "verified" if self.is_fresh(max_age_days, today) else "stale"

    def publishable(self, max_age_days=90, today=None):
        return self.effective_status(max_age_days, today) == "verified"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        return cls(**raw)
