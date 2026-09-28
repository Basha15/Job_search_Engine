"""
Auto Apply System
────────────────────────────────────────────────────────────────
Workflow:
  1. Pulls top matched jobs from Supabase (ATS score >= 70)
  2. Finds the best matching tailored resume for each job
  3. If no tailored resume exists — generates one on the spot
  4. Converts resume MD to PDF
  5. Auto-applies via:
     - LinkedIn Easy Apply (Playwright)
     - Naukri Quick Apply (Playwright)
     - Direct company portal (opens browser)
  6. Logs every application to Supabase applications table
  7. Sends Telegram alert for jobs needing manual apply

Usage:
    python auto_apply.py                  # apply to top 5 jobs
    python auto_apply.py --limit 20       # apply to top 20
    python auto_apply.py --dry-run        # simulate without applying
    python auto_apply.py --min-score 75   # only high confidence jobs
"""

import os
import re
import json
import logging
import asyncio
import argparse
import subprocess
from datetime import datetime, date, timezone
from dotenv import load_dotenv
from supabase import create_client
from ai_client import call_ai

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

DAILY_APPLY_LIMIT = int(os.environ.get("DAILY_APPLY_LIMIT", 20))
MIN_ATS_SCORE = float(os.environ.get("MIN_ATS_SCORE", 50))
RESUMES_DIR = "resumes"
LINKEDIN_LI_AT = os.environ.get("LINKEDIN_LI_AT_COOKIE", "")


# ── Step 1: Get jobs ready to apply ──────────────────────────────────────────
def get_jobs_to_apply(limit: int = 20, min_score: float = 50) -> list:
    """Fetch top matched jobs not yet applied to."""
    res = supabase.table("jobs") \
        .select("id, title, company, location, is_remote, ats_score, apply_url, platform, required_skills, missing_skills, matched_keywords, description_raw") \
        .eq("status", "matched") \
        .gte("ats_score", min_score) \
        .order("ats_score", desc=True) \
        .limit(limit) \
        .execute()
    return res.data or []


# ── Step 2: Find best matching resume ────────────────────────────────────────
def find_best_resume(job: dict) -> dict:
    """
    Finds the best tailored resume for a job.
    Matches by target_role keywords against job title.
    Returns resume dict with content_md and version_tag.
    """
    job_title = job["title"].lower()
    job_skills = [s.lower() for s in (job.get("required_skills") or [])]

    # Pull all resume versions from Supabase
    res = supabase.table("resume_versions") \
        .select("id, version_tag, target_role, target_keywords, content_md") \
        .eq("is_active", True) \
        .execute()

    resumes = res.data or []

    if not resumes:
        return None

    # Score each resume against this job
    best_resume = None
    best_match_score = 0

    for resume in resumes:
        score = 0
        target_role = (resume.get("target_role") or "").lower()
        target_keywords = [k.lower() for k in (resume.get("target_keywords") or [])]

        # Title similarity
        job_words = set(job_title.split())
        role_words = set(target_role.split())
        title_overlap = len(job_words & role_words)
        score += title_overlap * 10

        # Keyword overlap
        keyword_overlap = len(set(job_skills) & set(target_keywords))
        score += keyword_overlap * 5

        if score > best_match_score:
            best_match_score = score
            best_resume = resume

    return best_resume if best_match_score > 0 else resumes[0]


# ── Step 3: Convert MD to PDF ─────────────────────────────────────────────────
def convert_md_to_pdf(resume_md: str, output_path: str) -> bool:
    """
    Converts Markdown resume to PDF.
    Uses markdown + weasyprint (pip install weasyprint markdown).
    Falls back to saving as .md if PDF conversion fails.
    """
    try:
        import markdown
        import weasyprint

        html_content = f"""
        <html>
        <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; font-size: 11px; color: #222; }}
            h1 {{ font-size: 20px; color: #1a1a2e; border-bottom: 2px solid #1a1a2e; padding-bottom: 5px; }}
            h2 {{ font-size: 13px; color: #16213e; border-bottom: 1px solid #ccc; margin-top: 15px; text-transform: uppercase; letter-spacing: 1px; }}
            ul {{ margin: 3px 0; padding-left: 18px; }}
            li {{ margin: 2px 0; }}
            p {{ margin: 3px 0; }}
            strong {{ color: #1a1a2e; }}
        </style>
        </head>
        <body>
        {markdown.markdown(resume_md, extensions=['tables'])}
        </body>
        </html>
        """

        weasyprint.HTML(string=html_content).write_pdf(output_path)
        log.info(f"  PDF saved: {output_path}")
        return True

    except ImportError:
        log.warning("  weasyprint not installed — saving as .md only")
        md_path = output_path.replace(".pdf", ".md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(resume_md)
        return False

    except Exception as e:
        log.warning(f"  PDF conversion failed: {e}")
        return False


# ── Step 4: LinkedIn Easy Apply ───────────────────────────────────────────────
async def apply_linkedin_easy(job: dict, resume_path: str, dry_run: bool = False) -> bool:
    """Auto-apply via LinkedIn Easy Apply using Playwright."""
    from playwright.async_api import async_playwright

    if dry_run:
        log.info(f"  [DRY RUN] Would Easy Apply to: {job['apply_url']}")
        return True

    if not LINKEDIN_LI_AT:
        log.warning("  LINKEDIN_LI_AT_COOKIE not set — cannot auto-apply on LinkedIn")
        return False

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()

        # Set LinkedIn session cookie
        await context.add_cookies([{
            "name": "li_at",
            "value": LINKEDIN_LI_AT,
            "domain": ".linkedin.com",
            "path": "/"
        }])

        page = await context.new_page()

        try:
            await page.goto(job["apply_url"], wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)

            # Look for Easy Apply button
            easy_btn = await page.query_selector(".jobs-apply-button--top-card")
            if not easy_btn:
                log.info(f"  No Easy Apply button found — manual apply needed")
                await browser.close()
                return False

            await easy_btn.click()
            await page.wait_for_timeout(2000)

            # Navigate through application steps
            for step in range(10):
                await page.wait_for_timeout(1000)

                # Check for submit button
                submit = await page.query_selector("button[aria-label='Submit application']")
                if submit:
                    await submit.click()
                    await page.wait_for_timeout(2000)
                    log.info(f"  [OK] Applied via LinkedIn Easy Apply!")
                    await browser.close()
                    return True

                # Click next step
                next_btn = await page.query_selector("button[aria-label='Continue to next step']")
                review_btn = await page.query_selector("button[aria-label='Review your application']")

                if next_btn:
                    await next_btn.click()
                elif review_btn:
                    await review_btn.click()
                else:
                    log.warning(f"  Stuck at step {step+1} — no next/submit button")
                    break

        except Exception as e:
            log.error(f"  LinkedIn Easy Apply error: {e}")
        finally:
            await browser.close()

    return False


# ── Step 5: Naukri Quick Apply ────────────────────────────────────────────────
async def apply_naukri(job: dict, dry_run: bool = False) -> bool:
    """Auto-apply on Naukri using saved profile."""
    from playwright.async_api import async_playwright

    if dry_run:
        log.info(f"  [DRY RUN] Would apply on Naukri: {job['apply_url']}")
        return True

    naukri_email = os.environ.get("NAUKRI_EMAIL", "")
    naukri_pass = os.environ.get("NAUKRI_PASSWORD", "")

    if not naukri_email or not naukri_pass:
        log.warning("  NAUKRI_EMAIL or NAUKRI_PASSWORD not set")
        return False

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # Login to Naukri
            await page.goto("https://www.naukri.com/nlogin/login", timeout=20000)
            await page.fill("#usernameField", naukri_email)
            await page.fill("#passwordField", naukri_pass)
            await page.click("button[type='submit']")
            await page.wait_for_timeout(3000)

            # Navigate to job
            await page.goto(job["apply_url"], timeout=20000)
            await page.wait_for_timeout(2000)

            # Click Apply
            apply_btn = await page.query_selector("button:has-text('Apply')")
            if apply_btn:
                await apply_btn.click()
                await page.wait_for_timeout(2000)
                log.info(f"  [OK] Applied on Naukri!")
                await browser.close()
                return True

        except Exception as e:
            log.error(f"  Naukri apply error: {e}")
        finally:
            await browser.close()

    return False


# ── Step 6: Log application to Supabase ──────────────────────────────────────
def log_application(job: dict, resume_version: str, applied_via: str, success: bool, notes: str = ""):
    """Save application record to Supabase."""
    try:
        status = "auto_applied" if success else "matched"

        # Insert application record
        supabase.table("applications").insert({
            "job_id": job["id"],
            "resume_version": resume_version,
            "applied_via": applied_via,
            "status": status,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }).execute()

        # Update job status
        supabase.table("jobs").update({
            "status": status
        }).eq("id", job["id"]).execute()

        log.info(f"  Logged application: {job['title']} @ {job['company']} -> {status}")

    except Exception as e:
        log.error(f"  Failed to log application: {e}")


# ── Send Telegram alert for manual jobs ──────────────────────────────────────
def send_manual_apply_alert(manual_jobs: list):
    """Alert via Telegram for jobs that need manual application."""
    if not manual_jobs:
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or token == "mock":
        log.info("Telegram not configured — skipping alert")
        return

    lines = ["[ALERT] Jobs Needing Manual Application:\n"]
    for job in manual_jobs[:10]:
        lines.append(f"- {job['title']} @ {job['company']}")
        lines.append(f"  Score: {job.get('ats_score',0):.0f}%")
        lines.append(f"  URL: {job.get('apply_url','N/A')}\n")

    message = "\n".join(lines)

    import urllib.request, urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
    }).encode()

    try:
        urllib.request.urlopen(url, data=data, timeout=5)
        log.info("  Telegram alert sent for manual jobs")
    except Exception as e:
        log.warning(f"  Telegram alert failed: {e}")


# ── Main orchestrator ─────────────────────────────────────────────────────────
async def run_auto_apply(limit: int = 20, min_score: float = 50, dry_run: bool = False):
    """Main auto-apply pipeline."""

    print(f"\n{'='*60}")
    print(f"  AUTO APPLY SYSTEM")
    print(f"  Limit: {limit} jobs | Min Score: {min_score}% | Dry Run: {dry_run}")
    print(f"{'='*60}\n")

    # Check daily limit
    today = date.today().isoformat()
    applied_today = supabase.table("applications") \
        .select("id", count="exact") \
        .gte("applied_at", f"{today}T00:00:00") \
        .execute()
    already_applied = applied_today.count or 0
    remaining = DAILY_APPLY_LIMIT - already_applied

    if remaining <= 0:
        print(f"  Daily limit ({DAILY_APPLY_LIMIT}) reached. Come back tomorrow!")
        return

    print(f"  Applied today: {already_applied}/{DAILY_APPLY_LIMIT} | Remaining: {remaining}\n")
    limit = min(limit, remaining)

    # Get jobs
    jobs = get_jobs_to_apply(limit=limit + 5, min_score=min_score)

    if not jobs:
        print(f"  No jobs with ATS score >= {min_score}% found.")
        print(f"  Run: py -3.12 orchestrator.py --run daily")
        print(f"  Then: py -3.12 resume_optimizer.py")
        return

    print(f"  Found {len(jobs)} jobs ready to apply:\n")
    for i, job in enumerate(jobs[:limit]):
        print(f"  {i+1}. [{job.get('ats_score',0):.0f}%] {job['title']} @ {job['company']} ({job.get('platform','').upper()})")

    print(f"\n  Starting applications...\n")

    auto_applied = []
    manual_needed = []
    applied_count = 0

    for job in jobs[:limit]:
        if applied_count >= limit:
            break

        print(f"\n[{applied_count+1}/{limit}] {job['title']} @ {job['company']}")
        print(f"  ATS Score: {job.get('ats_score',0):.0f}% | Platform: {job.get('platform','').upper()}")
        print(f"  URL: {job.get('apply_url','N/A')}")

        # Find best matching resume
        best_resume = find_best_resume(job)

        if best_resume:
            print(f"  Resume matched: {best_resume.get('version_tag','unknown')}")
        else:
            print(f"  No tailored resume found — generating one now...")
            try:
                from resume_optimizer import generate_tailored_resume, save_resume
                base_resume = open(os.environ.get("BASE_RESUME_PATH","resume_base.md"), encoding="utf-8").read()
                resume_data = generate_tailored_resume(job, base_resume)
                filepath = save_resume(job, resume_data)
                # Reload from DB
                best_resume = find_best_resume(job)
                print(f"  [OK] Resume generated and saved")
            except Exception as e:
                log.warning(f"  Could not generate resume: {e}")

        resume_md = best_resume.get("content_md","") if best_resume else ""
        resume_version = best_resume.get("version_tag","base") if best_resume else "base"

        # Convert to PDF
        os.makedirs(RESUMES_DIR, exist_ok=True)
        pdf_path = os.path.join(RESUMES_DIR, f"{resume_version}.pdf")
        convert_md_to_pdf(resume_md, pdf_path)

        # Apply based on platform
        success = False
        apply_method = "manual"

        platform = job.get("platform","").lower()

        if platform == "linkedin":
            print(f"  Attempting LinkedIn Easy Apply...")
            success = await apply_linkedin_easy(job, pdf_path, dry_run=dry_run)
            apply_method = "linkedin_easy_apply"

        elif platform == "naukri":
            print(f"  Attempting Naukri Quick Apply...")
            success = await apply_naukri(job, dry_run=dry_run)
            apply_method = "naukri_quick_apply"

        else:
            print(f"  Platform '{platform}' needs manual apply")
            manual_needed.append(job)
            log_application(job, resume_version, "manual_needed", False,
                          notes=f"Platform {platform} needs manual apply")
            continue

        if success:
            log_application(job, resume_version, apply_method, True)
            auto_applied.append(job)
            applied_count += 1
            print(f"  [OK] Successfully applied!")
        else:
            manual_needed.append(job)
            log_application(job, resume_version, "manual_needed", False,
                          notes="Auto-apply failed — needs manual")
            print(f"  [!] Auto-apply failed — added to manual queue")

    # Final summary
    print(f"\n{'='*60}")
    print(f"  APPLY SUMMARY")
    print(f"{'='*60}")
    print(f"  Auto-applied: {len(auto_applied)}")
    print(f"  Manual needed: {len(manual_needed)}")

    if auto_applied:
        print(f"\n  Auto-applied to:")
        for job in auto_applied:
            print(f"    [OK] {job['title']} @ {job['company']}")

    if manual_needed:
        print(f"\n  Manual apply needed (open these URLs):")
        for job in manual_needed:
            print(f"    - {job['title']} @ {job['company']}")
            print(f"      {job.get('apply_url','N/A')}")

    # Send Telegram alert for manual jobs
    send_manual_apply_alert(manual_needed)

    print(f"\n  Your resume files are in: {os.path.abspath(RESUMES_DIR)}/")
    print(f"{'='*60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto Apply to matched jobs")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max jobs to apply to (default: 20)")
    parser.add_argument("--min-score", type=float, default=50,
                        help="Minimum ATS score (default: 50)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate without actually applying")
    args = parser.parse_args()

    asyncio.run(run_auto_apply(
        limit=args.limit,
        min_score=args.min_score,
        dry_run=args.dry_run
    ))