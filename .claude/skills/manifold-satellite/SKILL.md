---
name: manifold-satellite
description: >
  Manage the Manifold Markets satellite integration: API client, market matching,
  cross-platform signals, historical ingest, and calibration. Use when modifying
  Manifold-related code, adding new API endpoints, tuning matching thresholds,
  or debugging cross-platform signal quality.
---

# Manifold Intelligence Satellite

## Architecture Overview

Manifold Markets is integrated as a **satellite data source** that feeds a cross-platform
probability signal into the Value Assessment Engine (VAE). The signal flows:

```
ManifoldClient → ManifoldService (matching) → CrossPlatformSignal → VAE (cross_platform weight)
```

## Key Files

| File | Purpose |
|------|---------|
| `app/models/manifold.py` | Pydantic v2 models (ManifoldMarket, ManifoldBet, ManifoldComment, MarketMatch, CrossPlatformSignal) |
| `app/clients/manifold_client.py` | Async httpx client for Manifold v0 API (rate-limited, retries) |
| `app/services/manifold_service.py` | Market matching (TF-IDF cosine similarity) + signal generation |
| `app/valuation/engine.py` | VAE integration point — `cross_platform_signal` param on `assess()` |
| `app/core/yaml_config.py` | `ManifoldConfig` under `IntelligenceConfig` |
| `app/core/dependencies.py` | `get_manifold_service()` — returns None when disabled |
| `app/execution/engine.py` | `_fetch_manifold_signals()` — cadence-controlled polling in tick() |

## API Endpoints

Base URL: `https://api.manifold.markets/v0` (no auth needed for reads)

- `GET /search-markets?term=...&limit=20` — search by query
- `GET /market/{id}` — single market details
- `GET /slug/{slug}` — market by slug
- `GET /bets?contractId=...&limit=1000` — trade history
- `GET /comments?contractId=...` — market comments
- `GET /markets?limit=500&before=...` — paginated listing

## Market Matching

Uses scikit-learn `TfidfVectorizer` + `cosine_similarity` on question text.
- Threshold: `match_confidence_threshold` in config (default: 0.6)
- Filters: `min_manifold_volume`, `min_unique_bettors`
- Cache: in-memory dict with 1-hour TTL
- Resolved markets are skipped

## Signal Flow in VAE

`CrossPlatformSignal.signal_value` = Manifold probability (0-1), used directly as a fair-value
estimate with weight `cross_platform: 0.10` in `WeightsConfig`. Confidence scales with divergence:
- |divergence| > 0.10 → confidence 0.6
- |divergence| <= 0.10 → confidence 0.3

## Configuration

```yaml
intelligence:
  manifold:
    enabled: false  # must be true to activate
    base_url: https://api.manifold.markets/v0
    rate_limit: 10
    poll_interval_minutes: 30
    match_confidence_threshold: 0.6
    min_manifold_volume: 1000.0
    min_unique_bettors: 10
```

## Scripts

- `scripts/ingest_manifold.py` — bulk import resolved markets into ResolutionDB
  - `python scripts/ingest_manifold.py --limit 5000 --min-volume 500`
- `scripts/build_calibration.py` — compute calibration curves from resolution data
  - `python scripts/build_calibration.py --source manifold --output data/calibration_curves.json`

## Testing

- `tests/test_clients/test_manifold_client.py` — client with respx mocks
- `tests/test_services/test_manifold_service.py` — matching + signal generation
- `tests/test_valuation/test_engine.py` — VAE cross_platform signal integration
- `tests/test_valuation/test_base_rate.py` — DB source field tests

## Common Tasks

### Add a new Manifold API method
1. Add method to `ManifoldClient` following existing pattern
2. Add model to `manifold.py` if needed
3. Add test with respx mock

### Tune matching quality
- Adjust `match_confidence_threshold` in config
- Consider adding `sentence-transformers` for semantic matching (not yet integrated)
- Check `ManifoldService._compute_similarity()` for the TF-IDF logic

### Debug signal quality
- Check `ManifoldService.get_cross_platform_signal()` for divergence/confidence computation
- Check VAE `_compute_fair_value()` cross_platform block
- Look at `EdgeSource(name="cross_platform")` in valuation results
