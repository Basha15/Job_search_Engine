"""
ATS Batch Processor
────────────────────────────────────────
Scores all unscored jobs in Supabase one by one.
Handles Gemini rate limits with automatic delays.

Usage:
    python run_ats_batch.py           # score all unscored jobs
    python run_ats_batch.py --limit 20  # score 20 jobs only
"""

import os
import time
import logging
import argparse
from dotenv import load_dotenv
from supabase import create_client
from ats_matcher import process_job_for_ats

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

def run_ats_batch(limit: int = 50):
    print(f"\n{'='*56}")
    print(f"  ATS BATCH PROCESSOR")
    print(f"{'='*56}")

    # Get all unscored jobs that have a description
    res = supabase.table("jobs") \
        .select("id, title, company, description_raw") \
        .eq("status", "scraped") \
        .is_("ats_score", "null") \
        .not_.is_("description_raw", "null") \
        .limit(limit) \
        .execute()

    jobs = res.data or []

    if not jobs:
        # Also try jobs with very short descriptions skipped earlier
        res2 = supabase.table("jobs") \
            .select("id, title, company, description_raw") \
            .eq("status", "scraped") \
            .not_.is_("description_raw", "null") \
            .limit(limit) \
            .execute()
        jobs = res2.data or []

    if not jobs:
        print(f"\n  No unscored jobs found in database.")
        print(f"  Run scraper first: py -3.12 orchestrator.py --run daily")
        return

    print(f"\n  Found {len(jobs)} jobs to score\n")

    scored = 0
    matched = 0
    failed = 0

    for i, job in enumerate(jobs):
        jd = job.get("description_raw", "")
        if not jd or len(jd.strip()) < 40:
            log.info(f"  [{i+1}/{len(jobs)}] Skipping (no description): {job['title']}")
            continue

        print(f"\n  [{i+1}/{len(jobs)}] {job['title']} @ {job['company']}")

        try:
            result = process_job_for_ats(
                job_id=job["id"],
                jd_text=jd,
                job_title=job["title"],
                company=job["company"]
            )
            scored += 1
            if result["qualifies"]:
                matched += 1
                print(f"    Score: {result['score']:.1f}/100 -> MATCHED")
            else:
                print(f"    Score: {result['score']:.1f}/100 -> below threshold")

            # Wait between calls to respect Gemini free tier (15 RPM)
            if i < len(jobs) - 1:
                print(f"    Waiting 5s before next job...")
                time.sleep(5)

        except Exception as e:
            failed += 1
            log.error(f"    Failed: {e}")
            print(f"    Waiting 15s after error...")
            time.sleep(15)

    # Final summary
    print(f"\n{'='*56}")
    print(f"  BATCH COMPLETE")
    print(f"{'='*56}")
    print(f"  Total processed: {scored}")
    print(f"  Matched (score>=40): {matched}")
    print(f"  Failed: {failed}")
    print(f"\n  Now run resume optimizer:")
    print(f"  py -3.12 resume_optimizer.py --min-score 50")
    print(f"{'='*56}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50,
                        help="Max jobs to score (default: 50)")
    args = parser.parse_args()
    run_ats_batch(limit=args.limit)