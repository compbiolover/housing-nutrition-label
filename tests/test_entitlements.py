#!/usr/bin/env python3
"""Plans, API keys and the daily usage ledger.

No network and no FastAPI — this module is deliberately importable on its own,
so these run everywhere.

Run directly:  python tests/test_entitlements.py
"""

import contextlib
import os

from housing_label import entitlements as ent


@contextlib.contextmanager
def _env(**pairs):
    """Set (or clear, with None) env vars and reload the module's caches.

    Reloading on the way out matters as much as on the way in: the registry is
    process-global, so a test that left one configured would leak into every
    test after it.
    """
    prior = {k: os.environ.get(k) for k in pairs}
    try:
        for k, v in pairs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ent.reload()
        yield
    finally:
        for k, v in prior.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ent.reload()


def test_no_keys_configured_is_anonymous_and_unmetered():
    """The self-hosting contract, asserted directly.

    README promises the licence lets you run this yourself. An instance with no
    keys configured must therefore hand every caller an unmetered anonymous plan
    — not a smaller version of the service that existed before this module.
    """
    with _env(HOUSING_LABEL_KEYS=None, ANON_DAILY_SCORES=None):
        assert ent.registry() == {}
        anon = ent.plan_for(None)
        assert anon is not None and anon.name == "anonymous"
        assert anon.daily_scores == 0 and anon.metered is False
        # Blank and whitespace-only are "no key", not "bad key".
        for blank in ("", "   ", None):
            assert ent.plan_for(blank).name == "anonymous"


def test_key_resolves_to_its_plan_and_an_unknown_key_is_none():
    """None is reserved for "supplied a key, and it isn't one".

    Silently downgrading an unrecognised key to anonymous is the failure mode
    worth designing against: a customer whose key was mistyped or rotated would
    read their own downgrade as the service being slow.
    """
    with _env(HOUSING_LABEL_KEYS="pro:k_live_abc, basic:k_live_def"):
        assert ent.plan_for("k_live_abc").name == "pro"
        assert ent.plan_for("k_live_def").name == "basic"
        assert ent.plan_for("k_live_abc").daily_scores == ent.PLANS["pro"].daily_scores
        assert ent.plan_for("k_live_nope") is None
        assert ent.plan_for("K_LIVE_ABC") is None, "keys are case-sensitive"
        assert ent.plan_for(None).name == "anonymous"
        # Surrounding whitespace on the wire is incidental, not a different key.
        assert ent.plan_for("  k_live_abc  ").name == "pro"


def test_registry_holds_digests_and_never_the_key():
    """A key must not survive parsing. The digest is the identity everywhere
    downstream — bucket, ledger row, /usage — so no log line or error body can
    carry one even by accident."""
    secret = "k_live_do_not_leak"
    with _env(HOUSING_LABEL_KEYS=f"pro:{secret}"):
        reg = ent.registry()
        assert len(reg) == 1
        (digest,) = reg
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
        assert secret not in digest
        assert secret not in repr(reg)
        assert ent.key_id(secret) == digest
        assert ent.key_id(None) == "" and ent.key_id("  ") == ""


def test_malformed_entries_are_skipped_rather_than_fatal():
    """A typo in a dashboard variable must not take the service down — the same
    call api._env_num makes for the numeric knobs. The good entries still load."""
    spec = "garbage, :nokey, nosuchplan:k_x, pro:, basic:k_good,, partner:k_part"
    with _env(HOUSING_LABEL_KEYS=spec):
        reg = ent.registry()
        assert ent.plan_for("k_good").name == "basic"
        assert ent.plan_for("k_part").name == "partner"
        assert ent.plan_for("k_x") is None, "an unknown plan name issues no key"
        assert len(reg) == 2, reg
    # Newlines are a separator too — a multi-line dashboard value is common.
    with _env(HOUSING_LABEL_KEYS="pro:k_one\nbasic:k_two"):
        assert ent.plan_for("k_one").name == "pro"
        assert ent.plan_for("k_two").name == "basic"


def test_anonymous_plan_name_cannot_be_issued_as_a_key():
    """"anonymous" is what you get *without* a key. Naming it in the registry is
    a configuration mistake, not a way to mint a key that grants nothing."""
    with _env(HOUSING_LABEL_KEYS="anonymous:k_pointless"):
        assert ent.registry() == {}
        assert ent.plan_for("k_pointless") is None


def test_anonymous_allowance_is_configurable_and_defaults_to_unmetered():
    with _env(ANON_DAILY_SCORES="250"):
        assert ent.anonymous().daily_scores == 250
        assert ent.anonymous().metered is True
    with _env(ANON_DAILY_SCORES="0"):
        assert ent.anonymous().metered is False
    # A malformed or negative value falls back to unmetered rather than raising.
    for bad in ("not-a-number", "-5", ""):
        with _env(ANON_DAILY_SCORES=bad):
            assert ent.anonymous().daily_scores == 0, bad


def test_ledger_charges_and_reports_the_remainder():
    led = ent.UsageLedger()
    allowed, used, remaining = led.charge("caller", 3, 10)
    assert (allowed, used, remaining) == (True, 3, 7)
    allowed, used, remaining = led.charge("caller", 7, 10)
    assert (allowed, used, remaining) == (True, 10, 0)
    assert led.used("caller") == 10


def test_a_refused_charge_does_not_burn_the_remainder():
    """A caller who asks for six scenarios with four left should be able to come
    back and ask for four — not discover that the refusal ate them."""
    led = ent.UsageLedger()
    led.charge("caller", 6, 10)
    allowed, used, remaining = led.charge("caller", 6, 10)
    assert allowed is False
    assert used == 6 and remaining == 4, "the refusal must not increment"
    assert led.charge("caller", 4, 10) == (True, 10, 0)


def test_unmetered_plans_still_count_but_never_refuse():
    """Counting an unmetered caller is what makes /usage meaningful for them,
    and what would make a future invoice possible. It must never refuse."""
    led = ent.UsageLedger()
    for _ in range(3):
        allowed, _used, remaining = led.charge("partner", 1_000_000, 0)
        assert allowed is True and remaining is None
    assert led.used("partner") == 3_000_000


def test_callers_do_not_share_a_row():
    led = ent.UsageLedger()
    led.charge("a", 5, 10)
    assert led.charge("b", 9, 10) == (True, 9, 1), "b must not inherit a's spend"
    assert led.used("a") == 5 and led.used("b") == 9
    # Anonymous callers share the empty identity by design — there is no key to
    # tell them apart, and the per-IP rate limit is what separates them.
    led.charge("", 2, 0)
    assert led.used("") == 2


def test_the_day_rolls_over_and_drops_yesterday():
    led = ent.UsageLedger()
    real = ent._utc_day
    try:
        ent._utc_day = lambda: "2026-08-09"
        led = ent.UsageLedger()
        led.charge("caller", 9, 10)
        assert led.used("caller") == 9 and led.day == "2026-08-09"
        ent._utc_day = lambda: "2026-08-10"
        assert led.used("caller") == 0, "a new UTC day starts empty"
        assert led.day == "2026-08-10"
        assert led.charge("caller", 10, 10) == (True, 10, 0)
    finally:
        ent._utc_day = real


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
