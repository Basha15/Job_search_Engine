"""
Daily Orchestrator & Notification System
────────────────────────────────────────────────────────────────
Master runner that chains all modules:
  1. Scrape jobs (all platforms)
  2. Run ATS matching on new jobs
  3. Auto-apply to top matches
  4. Send cold outreach emails
  5. Publish due LinkedIn posts
  6. Send daily summary via Telegram or Email

Schedule via:
  - Cron: 0 8 * * * python orchestrator.py --run daily
  - GitHub Actions: .github/workflows/daily_run.yml
  - Modal.com: modal run orchestrator.py

Dependencies: all previous scripts + python-telegram-bot
"""

import os
import json
import logging
import asyncio
from datetime import datetime, date, timezone
from dotenv import load_dotenv

os.makedirs("logs", exist_ok=True)
from supabase import create_client
import anthropic

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"logs/run_{date.today().isoformat()}.log")
    ]
)
log = logging.getLogger(__name__)

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# ── Telegram Notification ──────────────────────────────────────────────────────
def send_telegram(message: str):
    """Send a message to your Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — skipping notification")
        return

    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }).encode()

    try:
        with urllib.request.urlopen(url, data=data, timeout=5) as r:
            log.info("  [NOTIFY] Telegram notification sent")
    except Exception as e:
        log.error(f"  Telegram send failed: {e}")


# ── Build Daily Summary ────────────────────────────────────────────────────────
def build_daily_summary() -> str:
    today = date.today().isoformat()

    # Pull today's stats
    run_log = supabase.table("daily_run_logs") \
        .select("*").eq("run_date", today).execute()
    stats = run_log.data[0] if run_log.data else {}

    # Top applied jobs
    applied = supabase.table("applications") \
        .select("*, jobs(title, company, location, ats_score)") \
        .gte("applied_at", f"{today}T00:00:00") \
        .order("applied_at", desc=True) \
        .limit(5) \
        .execute()

    # Emails sent today
    emails = supabase.table("outreach_logs") \
        .select("*, recruiters(name, company)") \
        .eq("status", "sent") \
        .gte("sent_at", f"{today}T00:00:00") \
        .execute()

    # High-priority manual jobs (score >= 80 but need manual apply)
    manual_needed = supabase.table("jobs") \
        .select("title, company, ats_score, apply_url") \
        .eq("status", "matched") \
        .gte("ats_score", 80) \
        .limit(5) \
        .execute()

    # Format message
    lines = [
        f"[BOT] *Daily Job Search Report — {today}*",
        "",
        f"[STATS] *Today's Numbers*",
        f"  • Jobs scraped: {stats.get('jobs_scraped', 0)}",
        f"  • Jobs matched (ATS ≥60): {stats.get('jobs_matched', 0)}",
        f"  • Auto-applied: {stats.get('jobs_applied', 0)}/20",
        f"  • Cold emails sent: {stats.get('emails_sent', 0)}/10",
        f"  • LinkedIn posts published: {stats.get('posts_published', 0)}",
        "",
    ]

    if applied.data:
        lines.append("[OK] *Auto-Applied Today*")
        for a in applied.data[:5]:
            job = a.get("jobs", {})
            score = job.get("ats_score", 0)
            lines.append(f"  • {job.get('title')} @ {job.get('company')} [{score:.0f}%]")
        lines.append("")

    if emails.data:
        lines.append("[EMAIL] *Cold Emails Sent*")
        for e in emails.data[:5]:
            rec = e.get("recruiters", {})
            lines.append(f"  • {rec.get('name')} @ {rec.get('company')}")
        lines.append("")

    if manual_needed.data:
        lines.append("[WARN] *Needs Manual Application (High Priority)*")
        for j in manual_needed.data:
            lines.append(f"  • {j['title']} @ {j['company']} [{j['ats_score']:.0f}%]")
            lines.append(f"    {j['apply_url']}")
        lines.append("")

    lines.append("_Job Search Engine by Basha [START]_")

    return "\n".join(lines)


# ── Main Daily Pipeline ────────────────────────────────────────────────────────
async def run_daily_pipeline():
    """
    Full daily execution sequence.
    Each step is isolated — failures don't block subsequent steps.
    """
    log.info("=" * 60)
    log.info(f"[START] DAILY JOB ENGINE RUN — {datetime.now(timezone.utc).isoformat()}")
    log.info("=" * 60)

    run_stats = {
        "jobs_scraped": 0,
        "jobs_matched": 0,
        "jobs_applied": 0,
        "emails_sent": 0,
        "posts_published": 0,
        "errors": []
    }

    # ── Step 1: Scrape jobs ──────────────────────────────────────────────────
    log.info("\n[1/5] [SCRAPE]  Scraping job boards...")
    try:
        from job_scraper import run_daily_scrape
        new_job_ids = await run_daily_scrape(
            platforms=["naukri", "linkedin", "ycombinator"],
            limit_per_query=25
        )
        run_stats["jobs_scraped"] = len(new_job_ids)
        log.info(f"     [OK] Scraped {len(new_job_ids)} new jobs")
    except Exception as e:
        log.error(f"     [ERR] Scraping failed: {e}")
        run_stats["errors"].append(f"scraping: {str(e)}")
        new_job_ids = []

    # ── Step 2: ATS matching ─────────────────────────────────────────────────
    log.info("\n[2/5] [ATS]  Running ATS matching...")
    try:
        from ats_matcher import process_job_for_ats

        # Get unscored scraped jobs
        unscored = supabase.table("jobs") \
            .select("id, title, company, description_raw") \
            .eq("status", "scraped") \
            .not_.is_("description_raw", "null") \
            .limit(50) \
            .execute()

        matched_count = 0
        for job in (unscored.data or []):
            if not job.get("description_raw"):
                continue
            result = process_job_for_ats(
                job_id=job["id"],
                jd_text=job["description_raw"],
                job_title=job["title"],
                company=job["company"]
            )
            if result["qualifies"]:
                matched_count += 1

        run_stats["jobs_matched"] = matched_count
        log.info(f"     [OK] Matched {matched_count} qualifying jobs")
    except Exception as e:
        log.error(f"     [ERR] ATS matching failed: {e}")
        run_stats["errors"].append(f"ats: {str(e)}")

    # ── Step 3: Auto-apply ───────────────────────────────────────────────────
    log.info("\n[3/5] [APPLY]  Auto-applying to top matches...")
    try:
        from job_scraper import auto_apply_linkedin_easy

        top_jobs = supabase.table("jobs") \
            .select("id, title, company, ats_score, apply_url, platform") \
            .eq("status", "matched") \
            .gte("ats_score", 75) \
            .order("ats_score", desc=True) \
            .limit(20) \
            .execute()

        applied_count = 0
        for job in (top_jobs.data or []):
            if applied_count >= 20:
                break

            # Only attempt Easy Apply for LinkedIn; others need manual
            if job["platform"] == "linkedin":
                success = await auto_apply_linkedin_easy(
                    job["apply_url"], job["id"], resume_url=""
                )
                if success:
                    applied_count += 1
            else:
                # Mark as needing manual apply for non-LinkedIn platforms
                supabase.table("jobs").update({
                    "status": "matched"  # stays matched, flagged for manual
                }).eq("id", job["id"]).execute()

        run_stats["jobs_applied"] = applied_count
        log.info(f"     [OK] Auto-applied to {applied_count} jobs")
    except Exception as e:
        log.error(f"     [ERR] Auto-apply failed: {e}")
        run_stats["errors"].append(f"auto_apply: {str(e)}")

    # ── Step 4: Cold email outreach ──────────────────────────────────────────
    log.info("\n[4/5] [EMAIL]  Sending cold outreach emails...")
    try:
        from cold_email import run_daily_outreach
        email_results = run_daily_outreach(
            send_method=os.environ.get("EMAIL_METHOD", "gmail"),
            dry_run=os.environ.get("DRY_RUN", "false").lower() == "true"
        )
        run_stats["emails_sent"] = len([r for r in (email_results or []) if r.get("status") == "sent"])
        log.info(f"     [OK] Sent {run_stats['emails_sent']} cold emails")
    except Exception as e:
        log.error(f"     [ERR] Cold email failed: {e}")
        run_stats["errors"].append(f"email: {str(e)}")

    # ── Step 5: LinkedIn posts ───────────────────────────────────────────────
    log.info("\n[5/5] [POST]  Publishing LinkedIn posts...")
    try:
        from linkedin_scheduler import run_daily_publisher
        published = run_daily_publisher()
        run_stats["posts_published"] = published
        log.info(f"     [OK] Published {published} LinkedIn posts")
    except Exception as e:
        log.error(f"     [ERR] LinkedIn posting failed: {e}")
        run_stats["errors"].append(f"linkedin: {str(e)}")

    # ── Persist run stats ────────────────────────────────────────────────────
    today = date.today().isoformat()
    try:
        existing = supabase.table("daily_run_logs").select("id").eq("run_date", today).execute()
        if existing.data:
            supabase.table("daily_run_logs").update({
                "jobs_scraped": run_stats["jobs_scraped"],
                "jobs_matched": run_stats["jobs_matched"],
                "jobs_applied": run_stats["jobs_applied"],
                "emails_sent": run_stats["emails_sent"],
                "posts_published": run_stats["posts_published"],
                "errors": run_stats["errors"]
            }).eq("run_date", today).execute()
        else:
            supabase.table("daily_run_logs").insert({
                "run_date": today,
                "jobs_scraped": run_stats["jobs_scraped"],
                "jobs_matched": run_stats["jobs_matched"],
                "jobs_applied": run_stats["jobs_applied"],
                "emails_sent": run_stats["emails_sent"],
                "posts_published": run_stats["posts_published"],
                "errors": run_stats["errors"]
            }).execute()
    except Exception as e:
        log.warning(f"Could not save run log: {e}")

    # ── Send Telegram summary ────────────────────────────────────────────────
    log.info("\n[NOTIFY] Sending daily summary notification...")
    summary = build_daily_summary()
    send_telegram(summary)

    log.info("\n" + "=" * 60)
    log.info(f"[OK] DAILY RUN COMPLETE")
    log.info(f"   Scraped: {run_stats['jobs_scraped']} | Matched: {run_stats['jobs_matched']}")
    log.info(f"   Applied: {run_stats['jobs_applied']} | Emailed: {run_stats['emails_sent']}")
    log.info(f"   Errors: {len(run_stats['errors'])}")
    log.info("=" * 60)

    return run_stats


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import os

    os.makedirs("logs", exist_ok=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--run", choices=["daily", "summary", "notify"],
                        default="daily")
    args = parser.parse_args()

    if args.run == "daily":
        asyncio.run(run_daily_pipeline())
    elif args.run == "summary":
        print(build_daily_summary())
    elif args.run == "notify":
        send_telegram(build_daily_summary())