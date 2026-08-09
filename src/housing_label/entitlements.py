#!/usr/bin/env python3
"""Caller identity for the hosted API: plans, API keys, and a daily usage ledger.

The API has always been anonymous. Every caller shares one per-IP token bucket
(``RATE_LIMIT``, default 30/minute), which is enough to keep one visitor from
exhausting the free government upstreams the scorer fans out to, and is not
enough to tell two callers apart. Nothing here counts per caller, so nothing
here can offer one caller more than another — not a raised limit, not a metered
allowance, not an embed budget.

This module is that missing waist. It resolves a request's API key to a
``Plan``, and it counts scoring passes per key per UTC day.

What a key buys, and what it does not
-------------------------------------
A key buys three things: a rate-limit bucket of your own (so a caller behind an
office NAT stops competing with its own colleagues for the anonymous bucket), a
daily scoring allowance that can be raised above whatever the deployment gives
anonymous callers, and an identity — which is what ``/usage`` reports and what
every future entitlement will hang off.

A key does **not** buy a higher burst rate, and that is a limitation of the
current limiter rather than a decision. slowapi evaluates ``default_limits``
without a request in hand (``LimitGroup.__iter__`` needs one, and
``Limiter._check_request_limit`` only supplies it for per-route dynamic limits,
which the middleware then never reaches), so the per-minute ceiling cannot be
varied per caller without replacing the limiter. Raising it per plan is a
follow-up. A ``Plan.rate_limit`` field would have looked like the feature while
enforcing nothing, so there isn't one.

Three things it deliberately is not
-----------------------------------
**Not a price list.** The numbers below are capacity tiers — what the host can
safely serve — not what anything costs. The free-tier shape (5,000 scores a day)
is calibrated off Walk Score's published free threshold, which is the closest
published comparable for a score served as an API; it is a starting point, not a
commitment.

**Not billing.** The ledger lives in this process's memory and starts empty after
every deploy, restart and scale event. That is honest for enforcing a daily
ceiling and useless as an invoice. Durable accounting needs storage the service
does not have — ``render.yaml`` declares no disk — and adding SQLite here would
buy the appearance of a ledger without the persistence, which is worse than
none. When there is a customer, there can be a database.

**Not a gate on self-hosting.** With ``HOUSING_LABEL_KEYS`` unset there is no
registry, every caller resolves to :data:`ANONYMOUS`, and the API behaves exactly
as it did before this module existed. The licence invites you to run it yourself
(README, "read it, run it, modify it, self-host it") and a self-hosted instance
that demanded keys would be a smaller promise than the one that was made. Keys
only ever *raise* a caller above anonymous; there is no way to configure one that
lowers anybody.

Configuring keys
----------------
One environment variable, entries separated by commas or newlines, each
``plan:key``::

    HOUSING_LABEL_KEYS="basic:k_live_7f3…, pro:k_live_9ab…"

Keys are hashed with SHA-256 as they are parsed and only the digest is kept, so
the plaintext exists in this process only for as long as it takes to read the
variable. The digest doubles as the caller's identity everywhere else — the
rate-limit bucket and the ledger row — so nothing this package writes, logs or
returns carries a key.

That is a guarantee about this code, not about the deployment, and the
difference matters. The API also accepts a key as ``?key=``, and a query string
is part of the request line: uvicorn's access log, any reverse proxy or load
balancer in front of it, browser history and the ``Referer`` header will all
capture it verbatim, and no amount of care in here can unwrite them. Steer
callers to the ``X-API-Key`` header, and treat a key that has travelled as a
query parameter as one to rotate.

``ANON_DAILY_SCORES`` sets the anonymous plan's daily allowance and defaults to
0, meaning unmetered — which is what anonymous callers have always had. An
operator running this as a service sets it to something finite, and keys then
lift named callers back above it. Leaving it alone is what makes a self-hosted
instance behave exactly as it did before this file existed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger("housing_label.entitlements")

KEYS_ENV = "HOUSING_LABEL_KEYS"
ANON_DAILY_ENV = "ANON_DAILY_SCORES"

ANONYMOUS_NAME = "anonymous"


@dataclass(frozen=True)
class Plan:
    """What a caller is entitled to: ``daily_scores`` scoring passes per UTC day,
    where 0 means unmetered.

    Deliberately one field. A flag for something not yet enforced — a burst rate
    the limiter can't vary, badge embedding, comparison endpoints — would read as
    a decision already made, and every endpoint open to anonymous callers today
    must stay open to them.
    """

    name: str
    daily_scores: int = 0

    @property
    def metered(self) -> bool:
        return self.daily_scores > 0


# Keyed tiers. The two finite ones bracket the published free/paid shapes in the
# nearest comparable market (see research/monetization-research.md); "partner" is
# unmetered, for someone scoring a book on a negotiated term.
PLANS: dict[str, Plan] = {
    "basic": Plan("basic", 5_000),
    "pro": Plan("pro", 50_000),
    "partner": Plan("partner", 0),
}

# Plans that may be assigned to a key. "anonymous" is what you get *without* one,
# so naming it in HOUSING_LABEL_KEYS is a configuration mistake worth reporting
# rather than a way to issue a key that grants nothing.
ASSIGNABLE = tuple(PLANS)


def key_id(raw_key: str | None) -> str:
    """The caller's stable identity: SHA-256 of the key, or "" when anonymous.

    Used as the rate-limit bucket and the ledger row, so a key is never the thing
    being passed around after this point.
    """
    if not raw_key or not raw_key.strip():
        return ""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


def _parse(spec: str | None) -> dict[str, Plan]:
    """Parse a ``plan:key`` registry spec into {key digest: Plan}.

    A malformed or unknown-plan entry is skipped with a warning rather than
    raising: a typo in a dashboard environment variable must not take the service
    down, which is the same call ``api._env_num`` makes for the numeric knobs.
    The warning names the entry's position and its plan, never its key — a log
    line is exactly the wrong place for one.

    The position counts every comma-separated segment, blanks included, so it
    matches what the operator is looking at. Numbering only the non-empty ones
    would drift the moment a value contains ``,,`` or a trailing comma, and an
    off-by-one pointer into a variable full of secrets is worse than none: it
    sends someone to inspect the wrong key.
    """
    registry: dict[str, Plan] = {}
    if not spec:
        return registry
    for i, entry in enumerate(spec.replace("\n", ",").split(","), start=1):
        entry = entry.strip()
        if not entry:
            continue
        name, sep, raw = entry.partition(":")
        name = name.strip().lower()
        if not sep or not raw.strip():
            log.warning("%s entry %d is not plan:key; skipped.", KEYS_ENV, i)
            continue
        plan = PLANS.get(name)
        if plan is None:
            log.warning("%s entry %d names unknown plan %r (choose one of: %s); "
                        "skipped.", KEYS_ENV, i, name, ", ".join(ASSIGNABLE))
            continue
        registry[key_id(raw)] = plan
    return registry


def _anon_allowance() -> int:
    """The anonymous daily allowance, 0 (unmetered) by default.

    A malformed value falls back to the default rather than raising — the same
    call ``api._env_num`` makes for the numeric knobs, and for the same reason: a
    typo in a dashboard variable must not take the service down.
    """
    raw = os.environ.get(ANON_DAILY_ENV, "").strip()
    if not raw:
        return 0
    try:
        return max(int(raw), 0)
    except ValueError:
        log.warning("Invalid %s=%r; anonymous callers stay unmetered.", ANON_DAILY_ENV, raw)
        return 0


_lock = threading.Lock()
_registry: dict[str, Plan] | None = None
_anonymous: Plan | None = None


def registry() -> dict[str, Plan]:
    """The configured {key digest: Plan} map, parsed once from the environment."""
    global _registry
    with _lock:
        if _registry is None:
            _registry = _parse(os.environ.get(KEYS_ENV))
            if _registry:
                log.info("%d API key(s) configured across %d plan(s).",
                         len(_registry), len({p.name for p in _registry.values()}))
        return _registry


def anonymous() -> Plan:
    """The plan for a caller who sent no key. Unmetered unless configured."""
    global _anonymous
    with _lock:
        if _anonymous is None:
            _anonymous = Plan(ANONYMOUS_NAME, _anon_allowance())
        return _anonymous


def reload() -> dict[str, Plan]:
    """Re-read the environment. For tests and for a restart-free key rotation."""
    global _registry, _anonymous
    with _lock:
        _registry = _anonymous = None
    anonymous()
    return registry()


def plan_for(raw_key: str | None) -> Plan | None:
    """Resolve a raw key to its Plan.

    The anonymous plan when no key was supplied, the key's Plan when it is
    registered, and **None when a key was supplied and is not registered** — a
    typo has to be distinguishable from anonymity, or a customer whose key stops
    working silently drops to the free tier and reads it as the service being
    slow.

    The lookup is a dict hit on a digest, not a ``compare_digest`` of the secret
    itself. Digest comparison is the thing timing attacks are about, and this
    never compares one: the key has already been through SHA-256 by the time it
    gets here, so what varies with timing is a hash-table probe on a value the
    attacker would have to have inverted the digest to influence.
    """
    if not raw_key or not raw_key.strip():
        return anonymous()
    return registry().get(key_id(raw_key))


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class UsageLedger:
    """Scoring passes charged per caller, for the current UTC day.

    In this process's memory, and gone when it restarts (see the module
    docstring). Rolls over on the UTC date rather than a per-key sliding window
    so a caller can be told plainly when their allowance resets.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day = _utc_day()
        self._counts: dict[str, int] = {}

    def _roll(self) -> None:
        """Drop yesterday wholesale. Caller holds the lock."""
        today = _utc_day()
        if today != self._day:
            self._day, self._counts = today, {}

    def charge(self, caller: str, cost: int, allowance: int) -> tuple[bool, int, int | None]:
        """Charge ``cost`` passes, returning (allowed, used, remaining).

        ``remaining`` is None when the plan is unmetered. A refused charge does
        **not** increment: a caller who asks for six scenarios with four left
        should be able to come back and ask for four, not discover that the
        refusal ate them.
        """
        with self._lock:
            self._roll()
            used = self._counts.get(caller, 0)
            if allowance <= 0:                       # unmetered
                self._counts[caller] = used + cost
                return True, used + cost, None
            if used + cost > allowance:
                return False, used, allowance - used
            self._counts[caller] = used + cost
            return True, used + cost, allowance - (used + cost)

    def used(self, caller: str) -> int:
        with self._lock:
            self._roll()
            return self._counts.get(caller, 0)

    @property
    def day(self) -> str:
        with self._lock:
            self._roll()
            return self._day

    def clear(self) -> None:
        with self._lock:
            self._counts = {}


ledger = UsageLedger()
