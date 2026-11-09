"""Backward-compatibility module for DynastyDealerClient redirecting to KtcClient."""

from __future__ import annotations

from ff.values.ktc import (
    KTC_VALUES_TTL as DEALER_VALUES_TTL,
    KTC_VALUES_URL as DEALER_VALUES_URL,
    KtcClient,
)

DynastyDealerClient = KtcClient

__all__ = ["DynastyDealerClient", "DEALER_VALUES_URL", "DEALER_VALUES_TTL"]
