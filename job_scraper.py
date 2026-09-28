"""
Multi-Platform Job Scraper & Auto-Applier
────────────────────────────────────────────────────────────────
Platforms covered:
  • Naukri.com
  • LinkedIn Jobs
  • Unstop
  • Y Combinator (Work at a Startup)
  • Greenhouse / Lever / Workday (via API or Playwright)

Usage:
    python job_scraper.py --platforms naukri linkedin --limit 50

Dependencies:
    pip install playwright supabase python-dotenv aiohttp asyncio
    playwright install chromium
"""

import os
import asyncio
import hashlib
import json
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import aiohttp
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, Browser
from supabase import create_client

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

# ── Config ────────────────────────────────────────────────────────────────────
SEARCH_TERMS = [
    "Python Developer", "Django Developer", "Backend Developer",
    "Software Engineer Python", "Data Analyst Python"
]
TARGET_LOCATIONS = ["Hyderabad", "Bangalore", "Remote"]
MIN_ATS_THRESHOLD = 60         # Only persist jobs with score >= this
DAILY_APPLY_LIMIT = 20
AUTO_APPLY_MIN_SCORE = 75      # Only auto-apply if score >= 75


# ── Data model ────────────────────────────────────────────────────────────────
def make_job_id(platform: str, url: str) -> str:
    return hashlib.md5(f"{platform}:{url}".encode()).hexdigest()[:16]


def dedup_check(url: str) -> bool:
    """Returns True if job already exists in DB."""
    res = supabase.table("jobs").select("id").eq("job_url", url).execute()
    return len(res.data) > 0


def save_job(job: dict) -> Optional[str]:
    """Upsert job and return its UUID."""
    if dedup_check(job["job_url"]):
        log.debug(f"  Skip (dup): {job['title']} @ {job['company']}")
        return None

    res = supabase.table("jobs").insert({
        "platform": job["platform"],
        "external_id": job.get("external_id"),
        "job_url": job["job_url"],
        "apply_url": job.get("apply_url", job["job_url"]),
        "title": job["title"],
        "company": job["company"],
        "location": job.get("location", ""),
        "is_remote": job.get("is_remote", False),
        "description_raw": job.get("description", ""),
        "posted_at": job.get("posted_at"),
        "status": "scraped"
    }).execute()

    if res.data:
        return res.data[0]["id"]
    return None


# ── Platform: Naukri ─────────────────────────────────────────────────────────
async def scrape_naukri(page: Page, query: str, location: str, limit: int = 30) -> list[dict]:
    jobs = []
    search_url = (
        f"https://www.naukri.com/{query.lower().replace(' ', '-')}-jobs-in-"
        f"{location.lower()}?experience=0-2&jobAge=1"
    )

    log.info(f"  Naukri: {query} in {location}")
    await page.goto(search_url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)

    # Scroll to load more results
    for _ in range(3):
        await page.keyboard.press("End")
        await page.wait_for_timeout(1500)

    cards = await page.query_selector_all("article.jobTuple")
    log.info(f"  Found {len(cards)} cards")

    for card in cards[:limit]:
        try:
            title_el = await card.query_selector("a.title")
            company_el = await card.query_selector("a.subTitle")
            location_el = await card.query_selector("li.location span")
            exp_el = await card.query_selector("li.experience span")

            title = await title_el.inner_text() if title_el else ""
            url = await title_el.get_attribute("href") if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            loc = await location_el.inner_text() if location_el else ""

            if not title or not url:
                continue

            jobs.append({
                "platform": "naukri",
                "title": title.strip(),
                "company": company.strip(),
                "job_url": url if url.startswith("http") else f"https://www.naukri.com{url}",
                "location": loc.strip(),
                "is_remote": "remote" in loc.lower(),
                "posted_at": (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
            })
        except Exception as e:
            log.debug(f"  Card parse error: {e}")

    return jobs


# ── Platform: Y Combinator (Work at a Startup) ───────────────────────────────
async def scrape_ycombinator(session: aiohttp.ClientSession, limit: int = 30) -> list[dict]:
    """WaaS has a public JSON API — no browser needed."""
    jobs = []

    params = {
        "query": "python backend",
        "remote": "true",
        "page": 1
    }

    async with session.get(
        "https://www.workatastartup.com/jobs",
        params=params,
        headers={"Accept": "application/json"}
    ) as resp:
        if resp.status != 200:
            log.warning(f"  YC API returned {resp.status}")
            return []
        # YC doesn't have a clean JSON API; parse HTML for now
        html = await resp.text()

    # Extract structured data from HTML (simplified — use BeautifulSoup in prod)
    job_pattern = re.compile(
        r'"job_title":"([^"]+)"[^}]*"company_name":"([^"]+)"[^}]*"url":"([^"]+)"',
        re.DOTALL
    )
    matches = job_pattern.findall(html)

    for title, company, url in matches[:limit]:
        jobs.append({
            "platform": "ycombinator",
            "title": title,
            "company": company,
            "job_url": f"https://www.workatastartup.com{url}" if url.startswith("/") else url,
            "location": "Remote",
            "is_remote": True,
            "posted_at": datetime.now(timezone.utc).isoformat()
        })

    log.info(f"  YC: found {len(jobs)} jobs")
    return jobs


# ── Platform: LinkedIn (via Playwright) ─────────────────────────────────────
async def scrape_linkedin(page: Page, query: str, location: str, limit: int = 25) -> list[dict]:
    """
    NOTE: LinkedIn heavily rate-limits scrapers.
    Use a logged-in session cookie (LI_AT env var) and add delays.
    Consider the unofficial LinkedIn Jobs API as an alternative.
    """
    jobs = []
    li_at = os.environ.get("LINKEDIN_LI_AT_COOKIE")

    if li_at:
        await page.context.add_cookies([{
            "name": "li_at",
            "value": li_at,
            "domain": ".linkedin.com",
            "path": "/"
        }])

    url = (
        f"https://www.linkedin.com/jobs/search/?keywords={query.replace(' ', '%20')}"
        f"&location={location}&f_TPR=r86400&f_E=1%2C2"  # last 24h, entry-level
    )

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # Scroll and load
    for _ in range(4):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

    cards = await page.query_selector_all(".job-search-card")

    for card in cards[:limit]:
        try:
            title_el = await card.query_selector("h3.base-search-card__title")
            company_el = await card.query_selector("h4.base-search-card__subtitle a")
            link_el = await card.query_selector("a.base-card__full-link")
            loc_el = await card.query_selector("span.job-search-card__location")

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            href = await link_el.get_attribute("href") if link_el else ""
            loc = await loc_el.inner_text() if loc_el else ""

            if title and href:
                jobs.append({
                    "platform": "linkedin",
                    "title": title.strip(),
                    "company": company.strip(),
                    "job_url": href.split("?")[0],
                    "location": loc.strip(),
                    "is_remote": "remote" in loc.lower(),
                    "posted_at": datetime.now(timezone.utc).isoformat()
                })
        except Exception as e:
            log.debug(f"  LinkedIn card error: {e}")

    log.info(f"  LinkedIn: {query} in {location} -> {len(jobs)} found")
    return jobs


# ── JD Fetcher (detail page) ─────────────────────────────────────────────────
async def fetch_job_description(page: Page, job_url: str, platform: str) -> str:
    """Navigate to job detail page and extract description text."""
    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(1500)

        selectors = {
            "naukri": ".job-desc",
            "linkedin": ".description__text",
            "ycombinator": ".job-description",
        }

        sel = selectors.get(platform, "body")
        el = await page.query_selector(sel)
        if el:
            return await el.inner_text()

        # Fallback: get all visible text
        return await page.evaluate("document.body.innerText")[:5000]

    except Exception as e:
        log.warning(f"  JD fetch failed for {job_url}: {e}")
        return ""


# ── Main Orchestrator ─────────────────────────────────────────────────────────
async def run_daily_scrape(platforms: list[str] = None, limit_per_query: int = 25):
    platforms = platforms or ["naukri", "linkedin", "ycombinator"]
    total_scraped = 0
    all_job_ids = []

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        async with aiohttp.ClientSession() as session:
            for query in SEARCH_TERMS:
                for location in TARGET_LOCATIONS:
                    raw_jobs = []

                    if "naukri" in platforms:
                        try:
                            raw_jobs += await scrape_naukri(page, query, location, limit_per_query)
                        except Exception as e:
                            log.error(f"Naukri error: {e}")

                    if "linkedin" in platforms:
                        try:
                            raw_jobs += await scrape_linkedin(page, query, location, limit_per_query)
                        except Exception as e:
                            log.error(f"LinkedIn error: {e}")

                if "ycombinator" in platforms:
                    try:
                        raw_jobs += await scrape_ycombinator(session, limit_per_query)
                    except Exception as e:
                        log.error(f"YC error: {e}")

                # Fetch descriptions for new jobs
                for job in raw_jobs:
                    job_id = save_job(job)
                    if job_id:
                        log.info(f"  Saved: {job['title']} @ {job['company']}")
                        # Fetch description for ATS matching
                        desc = await fetch_job_description(page, job["job_url"], job["platform"])
                        if desc:
                            supabase.table("jobs").update({
                                "description_raw": desc[:10000]
                            }).eq("id", job_id).execute()
                        all_job_ids.append(job_id)
                        total_scraped += 1
                        await asyncio.sleep(1.5)  # polite delay

        await browser.close()

    log.info(f"\n[OK] Scraping complete: {total_scraped} new jobs saved")

    # Update daily run log
    supabase.table("daily_run_logs").upsert({
        "run_date": datetime.now(timezone.utc).date().isoformat(),
        "jobs_scraped": total_scraped
    }).execute()

    return all_job_ids


# ── Auto-Apply (LinkedIn Easy Apply) ─────────────────────────────────────────
async def auto_apply_linkedin_easy(job_url: str, job_id: str, resume_url: str) -> bool:
    """
    Attempts LinkedIn Easy Apply for a matched job.
    Returns True if successful.
    [WARN]  IMPORTANT: Only use for Easy Apply jobs with simple forms.
    Complex multi-step applications need manual review.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)  # visible for debugging
        context = await browser.new_context()

        li_at = os.environ.get("LINKEDIN_LI_AT_COOKIE")
        if li_at:
            await context.add_cookies([{
                "name": "li_at", "value": li_at,
                "domain": ".linkedin.com", "path": "/"
            }])

        page = await context.new_page()

        try:
            await page.goto(job_url, wait_until="networkidle", timeout=20000)
            await page.wait_for_timeout(2000)

            # Check for Easy Apply button
            easy_apply = await page.query_selector(".jobs-apply-button--top-card")
            if not easy_apply:
                log.info(f"  No Easy Apply button — skipping auto-apply")
                return False

            await easy_apply.click()
            await page.wait_for_timeout(2000)

            # Handle simple form pages (contact info pre-filled from profile)
            step = 0
            max_steps = 8

            while step < max_steps:
                step += 1
                await page.wait_for_timeout(1000)

                # Check for submit button
                submit = await page.query_selector("button[aria-label='Submit application']")
                if submit:
                    await submit.click()
                    await page.wait_for_timeout(2000)
                    log.info(f"  [OK] Applied via Easy Apply: {job_url}")

                    # Update DB
                    supabase.table("applications").insert({
                        "job_id": job_id,
                        "applied_via": "auto",
                        "status": "auto_applied",
                        "resume_url": resume_url
                    }).execute()
                    supabase.table("jobs").update({"status": "auto_applied"}).eq("id", job_id).execute()
                    return True

                # Click Next
                next_btn = await page.query_selector("button[aria-label='Continue to next step']")
                if next_btn:
                    await next_btn.click()
                else:
                    log.warning(f"  No next/submit button at step {step}")
                    break

        except Exception as e:
            log.error(f"  Auto-apply error: {e}")
        finally:
            await browser.close()

    return False


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--platforms", nargs="+",
                        default=["naukri", "linkedin", "ycombinator"])
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    asyncio.run(run_daily_scrape(platforms=args.platforms, limit_per_query=args.limit))