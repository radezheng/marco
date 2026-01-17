from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AllocationTemplate:
    name: str
    asset_class_weights: dict[str, float]
    equity_bucket_weights: dict[str, float]
    overlays: dict[str, float]


TEMPLATES: dict[str, AllocationTemplate] = {
    "Risk-On": AllocationTemplate(
        name="Risk-On",
        asset_class_weights={
            "Equity": 0.60,
            "Rates": 0.10,
            "Credit": 0.15,
            "Cash": 0.05,
            "Gold&Commodities": 0.10,
        },
        equity_bucket_weights={
            "Tech+CommSvcs": 0.25,
            "ConsDisc": 0.15,
            "Industrials": 0.15,
            "Financials": 0.12,
            "Materials": 0.08,
            "Energy": 0.08,
            "HealthCare": 0.10,
            "Staples+Utilities+RE": 0.07,
        },
        overlays={"FX_HEDGE": 0.20},
    ),
    "Neutral": AllocationTemplate(
        name="Neutral",
        asset_class_weights={
            "Equity": 0.45,
            "Rates": 0.20,
            "Credit": 0.15,
            "Cash": 0.10,
            "Gold&Commodities": 0.10,
        },
        equity_bucket_weights={
            "Tech+CommSvcs": 0.18,
            "ConsDisc": 0.10,
            "Industrials": 0.12,
            "Financials": 0.12,
            "Materials": 0.08,
            "Energy": 0.06,
            "HealthCare": 0.14,
            "Staples+Utilities+RE": 0.20,
        },
        overlays={"FX_HEDGE": 0.50},
    ),
    "Risk-Off": AllocationTemplate(
        name="Risk-Off",
        asset_class_weights={
            "Equity": 0.25,
            "Rates": 0.40,
            "Credit": 0.05,
            "Cash": 0.20,
            "Gold&Commodities": 0.10,
        },
        equity_bucket_weights={
            "Tech+CommSvcs": 0.12,
            "ConsDisc": 0.05,
            "Industrials": 0.08,
            "Financials": 0.08,
            "Materials": 0.05,
            "Energy": 0.04,
            "HealthCare": 0.22,
            "Staples+Utilities+RE": 0.36,
        },
        overlays={"FX_HEDGE": 0.90},
    ),
}


def template_for_regime(regime: str) -> AllocationTemplate | None:
    if regime == "A":
        return TEMPLATES["Risk-On"]
    if regime == "B":
        return TEMPLATES["Neutral"]
    if regime == "C":
        return TEMPLATES["Risk-Off"]
    return None
