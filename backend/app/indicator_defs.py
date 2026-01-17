from __future__ import annotations

# Base series fetched from FRED public CSV.
# NOTE: Some series may be unavailable depending on FRED distribution; ingestion will skip missing ones.

FRED_BASE_SERIES: dict[str, str] = {
    # Liquidity components
    "walcl": "WALCL",  # Fed total assets
    "tga": "WTREGEN",  # Treasury General Account
    "rrp": "RRPONTSYD",  # Overnight Reverse Repo
    # Funding
    "sofr": "SOFR",
    "effr": "EFFR",
    "iorb": "IORB",
    # Rates (daily)
    "dgs10": "DGS10",
    # Volatility
    "vix": "VIXCLS",
    "vxv": "VXVCLS",  # 3M VIX (may be missing)
    # Credit
    "hy_oas": "BAMLH0A0HYM2",  # ICE BofA US High Yield OAS
    # USD (official Fed trade-weighted indices)
    "usd_twi_broad": "DTWEXBGS",
}

# Derived indicators (stored into observation table)
DERIVED_KEYS = {
    "synthetic_liquidity_level",
    "synthetic_liquidity_delta_w",
    "funding_spread",
    "treasury_realized_vol_20d",
    "vix_slope",
}
