"""
Periodic crawler / polling worker for StayTrace.
Iterates over active (non-terminal) parcels, queries latest tracking from Bright Data,
and resolves state updates in the database.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, List, Optional

from db.database import (
    init_db,
    list_parcels,
    get_parcel_with_events,
    save_parcel_with_events,
    log_scrape,
)
from pipeline.resolver import resolve_parcel_update, is_terminal_status
from scraper.brightdata import BrightDataClient, BrightDataError, BrightDataNotFoundError

logger = logging.getLogger("staytrace.crawler")

ACTIVE_STATUSES = [
    "pre_transit",
    "in_transit",
    "out_for_delivery",
    "failed_attempt",
    "exception",
    "unknown",
]


def crawl_active_parcels(
    db_path: Optional[str] = None,
    client: Optional[BrightDataClient] = None,
    limit: int = 100,
) -> Dict[str, int]:
    """
    Poll active parcels and update database.
    Returns summary statistics of the crawl run.
    """
    client = client or BrightDataClient()
    init_db(db_path=db_path)

    stats = {"processed": 0, "updated": 0, "errors": 0, "terminal": 0}

    all_parcels: List[Dict[str, Any]] = []
    seen = set()
    for st in ACTIVE_STATUSES:
        found = list_parcels(status=st, limit=limit, db_path=db_path)
        for p in found:
            tn = p["tracking_number"]
            if tn not in seen:
                seen.add(tn)
                all_parcels.append(p)

    logger.info("Found %d active parcels to crawl", len(all_parcels))

    for parcel_summary in all_parcels:
        tracking_number = parcel_summary["tracking_number"]
        carrier = parcel_summary.get("carrier", "other")
        stats["processed"] += 1

        try:
            full_existing = get_parcel_with_events(tracking_number, db_path=db_path)
            incoming = client.fetch_tracking(carrier, tracking_number)

            resolved_parcel, resolved_events, changed = resolve_parcel_update(
                existing_parcel=full_existing,
                incoming_parcel=incoming,
                existing_events=full_existing.get("events", []) if full_existing else [],
                incoming_events=incoming.get("events", []),
            )

            save_parcel_with_events(resolved_parcel, resolved_events, db_path=db_path)
            log_scrape(tracking_number, carrier, "success", db_path=db_path)

            if changed:
                stats["updated"] += 1
            if is_terminal_status(resolved_parcel.get("status")):
                stats["terminal"] += 1

        except BrightDataNotFoundError as e:
            logger.warning("Tracking number %s not found on carrier: %s", tracking_number, e)
            log_scrape(tracking_number, carrier, "not_found", error_message=str(e), db_path=db_path)
            stats["errors"] += 1
        except (BrightDataError, Exception) as e:
            logger.error("Failed to crawl parcel %s: %s", tracking_number, e)
            log_scrape(tracking_number, carrier, "failed", error_message=str(e), db_path=db_path)
            stats["errors"] += 1

    logger.info("Crawl finished: %s", stats)
    return stats


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
    )
    api_key = os.environ.get("BRIGHTDATA_API_KEY")
    if not api_key:
        logger.info("BRIGHTDATA_API_KEY is not configured; running in verification mode.")

    db_path = os.environ.get("DATABASE_PATH", "parcels.db")
    crawl_active_parcels(db_path=db_path)


if __name__ == "__main__":
    main()
