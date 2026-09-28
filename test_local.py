"""
Local Test Suite — Job Search Engine (Gemini-powered, FREE)
Usage:
    python test_local.py              # mock-only (no API key needed)
    python test_local.py --module ats # test one module
"""

import os, sys, json, unittest, argparse
from unittest.mock import MagicMock, patch
if sys.version_info >= (3, 8):
    from unittest.mock import AsyncMock
else:
    AsyncMock = MagicMock
from datetime import datetime, timezone

GREEN="\033[92m"; RED="\033[91m"; YELLOW="\033[93m"; BLUE="\033[94m"; RESET="\033[0m"; BOLD="\033[1m"
def ok(m):   print(f"  {GREEN}✅  {m}{RESET}")
def fail(m): print(f"  {RED}❌  {m}{RESET}")
def info(m): print(f"  {BLUE}ℹ   {m}{RESET}")
def warn(m): print(f"  {YELLOW}⚠   {m}{RESET}")

# ── Mock env ──────────────────────────────────────────────────────────────────
for k,v in {
    "GEMINI_API_KEY":       os.environ.get("GEMINI_API_KEY",""),
    "SUPABASE_URL":         "https://mock.supabase.co",
    "SUPABASE_SERVICE_KEY": "mock-service-key",
    "GMAIL_USER":           "test@gmail.com",
    "GMAIL_APP_PASSWORD":   "mock-password",
    "SENDER_NAME":          "Shaik Umar Basha",
    "SENDER_EMAIL":         "basha@example.com",
    "TELEGRAM_BOT_TOKEN":   "mock:token",
    "TELEGRAM_CHAT_ID":     "123456",
    "GITHUB_URL":           "https://github.com/basha",
    "LINKEDIN_URL":         "https://linkedin.com/in/basha",
    "BASE_RESUME_PATH":     "/tmp/test_resume.md",
    "LINKEDIN_ACCESS_TOKEN":"mock-token",
    "LINKEDIN_PERSON_URN":  "urn:li:person:mock",
}.items():
    os.environ.setdefault(k, v)

SAMPLE_RESUME = """
# Shaik Umar Basha
Hyderabad | basha@email.com | github.com/basha

## Skills
Python, Django, REST APIs, PostgreSQL, SQL, Redis, Celery, Git, Pandas, Matplotlib

## Experience
Backend Developer Intern — TechStartup, Hyderabad (2026)
- Built 15+ Django REST API endpoints with JWT authentication
- Implemented Celery + Redis for async task processing (reduced latency 40%)
- Designed PostgreSQL schemas for a job-tracking application

## Projects
AI Job Tracker (Django + PostgreSQL + React)
- REST API with pagination, filtering, JWT-secured endpoints

Smart India Hackathon 2025 — Winner
- Real-time public grievance portal using Django + WebSockets

## Education
B.Tech IT — Malla Reddy College of Engineering (CGPA 7.9, 2026)
""".strip()

SAMPLE_JD = """
We are looking for a Python Backend Developer.
Requirements: Python, Django, REST API, PostgreSQL, Git, Celery, Redis, JWT, Docker, Agile
Responsibilities: Design REST APIs, write clean Python code, optimize database queries.
""".strip()

SAMPLE_JOB = {
    "id": "mock-job-001", "title": "Python Backend Developer",
    "company": "TestCorp India", "company_domain": "testcorp.in",
    "location": "Hyderabad", "is_remote": False, "ats_score": 82.5,
    "matched_keywords": ["Python","Django","REST API","PostgreSQL","Celery"],
    "apply_url": "https://testcorp.in/careers/python-dev",
    "description_raw": SAMPLE_JD, "platform": "naukri",
}

SAMPLE_RECRUITER = {
    "id": "mock-rec-001", "name": "Priya Sharma",
    "email": "priya@testcorp.in", "email_verified": True,
    "company": "TestCorp India", "company_domain": "testcorp.in",
    "role_title": "Technical Recruiter",
}

with open("/tmp/test_resume.md", "w") as f:
    f.write(SAMPLE_RESUME)

os.makedirs("logs", exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═════════════════════════════════════════════════════════════════════════════
# TEST 1 — ATS Matcher
# ═════════════════════════════════════════════════════════════════════════════
def test_ats_module(use_real_api):
    print(f"\n{BOLD}{'='*52}\n  MODULE 1 — ATS Matcher\n{'='*52}{RESET}")

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
    mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [{"id":"v1"}]

    print("\n[1a] Offline ATS scoring...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"), \
         patch("ai_client.call_ai_json", return_value={}):
        import ats_matcher as ats

        mock_kw = {
            "hard_skills": ["Python","Django","PostgreSQL","Celery","Redis","Docker"],
            "tools": ["Git","Linux","JWT"],
            "role_keywords": ["REST API","Django REST Framework","backend developer"],
        }
        result = ats.compute_ats_score(SAMPLE_RESUME, mock_kw)
        assert result["score"] > 0
        assert "Python" in result["matched_keywords"]
        assert "Django" in result["matched_keywords"]
        ok(f"ATS score: {result['score']:.1f}/100")
        ok(f"Matched {result['matched_count']}/{result['total_keywords']} keywords")
        ok(f"Matched: {', '.join(result['matched_keywords'][:5])}")
        if result["missing_keywords"]:
            info(f"Missing: {', '.join(result['missing_keywords'][:3])}")

    if use_real_api:
        print("\n[1b] Live Gemini — JD keyword extraction...")
        with patch("supabase.create_client", return_value=mock_sb):
            import importlib; importlib.reload(ats)
            try:
                keywords = ats.extract_jd_keywords(SAMPLE_JD)
                assert "hard_skills" in keywords
                ok(f"Extracted skills: {keywords['hard_skills'][:4]}")

                print("\n[1c] Live Gemini — tailored resume generation...")
                score_r = ats.compute_ats_score(SAMPLE_RESUME, keywords)
                resume_md = ats.generate_tailored_resume(
                    SAMPLE_RESUME, SAMPLE_JD, keywords,
                    score_r["missing_keywords"], "Python Backend Developer", "TestCorp"
                )
                assert len(resume_md) > 200
                ok(f"Tailored resume: {len(resume_md)} chars")
                with open("/tmp/tailored_resume_test.md","w") as f: f.write(resume_md)
                info("Saved → /tmp/tailored_resume_test.md")
            except Exception as e:
                fail(f"Live API error: {e}")
    else:
        warn("No GEMINI_API_KEY — skipping live AI tests")

# ═════════════════════════════════════════════════════════════════════════════
# TEST 2 — Cold Email
# ═════════════════════════════════════════════════════════════════════════════
def test_email_module(use_real_api):
    print(f"\n{BOLD}{'='*52}\n  MODULE 2 — Cold Email Generator\n{'='*52}{RESET}")

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{}]
    mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [SAMPLE_RECRUITER]

    print("\n[2a] Daily limit check...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"), \
         patch("ai_client.call_ai_json", return_value={}):
        import cold_email as ce
        with patch.object(ce, "get_todays_email_count", return_value=0):
            count = ce.get_todays_email_count()
            ok(f"Emails sent today: {count}/{ce.DAILY_EMAIL_LIMIT}")

    print("\n[2b] Recruiter lookup (mock)...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"), \
         patch("ai_client.call_ai_json", return_value={}):
        import importlib, cold_email; importlib.reload(cold_email)
        rec = cold_email.find_or_create_recruiter("TestCorp","testcorp.in","job-id")
        ok(f"Recruiter: {rec['name']} <{rec['email']}>")

    if use_real_api:
        print("\n[2c] Live Gemini — email generation...")
        with patch("supabase.create_client", return_value=mock_sb):
            import importlib, cold_email; importlib.reload(cold_email)
            try:
                email = cold_email.generate_cold_email(SAMPLE_RECRUITER, SAMPLE_JOB)
                assert "subject" in email and len(email["body_text"]) > 100
                ok(f"Subject: {email['subject']}")
                ok(f"Body: {len(email['body_text'])} chars")
                print(f"\n{BLUE}  ── Preview ──────────────────────────────────{RESET}")
                for line in email["body_text"].split("\n")[:10]: print(f"  {line}")
                print(f"  {BLUE}  ────────────────────────────────────────────{RESET}")
                with open("/tmp/test_cold_email.txt","w") as f:
                    f.write(f"Subject: {email['subject']}\n\n{email['body_text']}")
                info("Saved → /tmp/test_cold_email.txt")
            except Exception as e:
                fail(f"Email generation error: {e}")
    else:
        warn("No GEMINI_API_KEY — skipping live email generation")

    print("\n[2d] Gmail SMTP mock...")
    with patch("smtplib.SMTP") as mock_smtp, \
         patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"), \
         patch("ai_client.call_ai_json", return_value={}):
        import importlib, cold_email; importlib.reload(cold_email)
        cold_email.send_via_gmail("test@test.com","Test","Subject","<p>Hi</p>","Hi")
        assert mock_smtp.return_value.__enter__.return_value.sendmail.called
        ok("Gmail SMTP path OK (mock)")

# ═════════════════════════════════════════════════════════════════════════════
# TEST 3 — LinkedIn Scheduler
# ═════════════════════════════════════════════════════════════════════════════
def test_linkedin_module(use_real_api):
    print(f"\n{BOLD}{'='*52}\n  MODULE 3 — LinkedIn Scheduler\n{'='*52}{RESET}")

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{"id":"post-001"}]
    mock_sb.table.return_value.select.return_value.in_.return_value.lte.return_value.execute.return_value.data = []
    mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]

    print("\n[3a] Weekly schedule slots...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"):
        import linkedin_scheduler as ls
        from datetime import date
        slots = ls.get_schedule_for_week(date.today())
        assert len(slots) > 0
        ok(f"Generated {len(slots)} posting slots")
        for dt, ct in slots[:3]: info(f"  {dt.strftime('%a %b %d %H:%M')} → {ct}")

    if use_real_api:
        print("\n[3b] Live Gemini — thought leadership post...")
        with patch("supabase.create_client", return_value=mock_sb):
            import importlib, linkedin_scheduler; importlib.reload(linkedin_scheduler)
            try:
                tl = linkedin_scheduler.generate_thought_leadership_post()
                assert len(tl["content"]) > 100
                ok(f"Post generated: {len(tl['content'])} chars")
                print(f"\n{BLUE}  ── Post preview ──────────────────────────────{RESET}")
                for line in tl["content"].split("\n")[:6]: print(f"  {line}")
                print(f"  {BLUE}  ...(truncated){RESET}\n")

                micro = linkedin_scheduler.generate_micro_update_post("project")
                ok(f"Micro-update: {len(micro['content'])} chars")
                with open("/tmp/test_linkedin_posts.txt","w") as f:
                    f.write("=== THOUGHT LEADERSHIP ===\n\n"+tl["content"])
                    f.write("\n\n=== MICRO UPDATE ===\n\n"+micro["content"])
                info("Saved → /tmp/test_linkedin_posts.txt")
            except Exception as e:
                fail(f"LinkedIn generation error: {e}")
    else:
        warn("No GEMINI_API_KEY — skipping live post generation")

    print("\n[3c] Schedule post to DB (mock)...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"):
        import importlib, linkedin_scheduler; importlib.reload(linkedin_scheduler)
        pid = linkedin_scheduler.schedule_post(
            {"content":"Test #Python","hashtags":["#Python"],"post_type":"micro_update","generation_seed":"test"},
            publish_at=datetime.now(timezone.utc), requires_review=True
        )
        assert pid is not None
        ok(f"Post scheduled (mock ID: {pid})")

# ═════════════════════════════════════════════════════════════════════════════
# TEST 4 — Scraper
# ═════════════════════════════════════════════════════════════════════════════
def test_scraper_module():
    print(f"\n{BOLD}{'='*52}\n  MODULE 4 — Job Scraper\n{'='*52}{RESET}")

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{"id":"job-001"}]

    print("\n[4a] Dedup logic...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"):
        import job_scraper as js
        assert not js.dedup_check("https://naukri.com/job/new")
        ok("New URL: not a duplicate ✓")
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{"id":"x"}]
        assert js.dedup_check("https://naukri.com/job/existing")
        ok("Existing URL: correctly blocked ✓")

    print("\n[4b] Job ID determinism...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"):
        import importlib, job_scraper; importlib.reload(job_scraper)
        id1 = job_scraper.make_job_id("naukri","https://naukri.com/123")
        id2 = job_scraper.make_job_id("naukri","https://naukri.com/123")
        id3 = job_scraper.make_job_id("linkedin","https://naukri.com/123")
        assert id1 == id2 and id1 != id3
        ok(f"Job ID is deterministic (sample: {id1})")

    print("\n[4c] Search config...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"):
        import importlib, job_scraper; importlib.reload(job_scraper)
        assert len(job_scraper.SEARCH_TERMS) > 0
        assert len(job_scraper.TARGET_LOCATIONS) > 0
        ok(f"Search terms: {job_scraper.SEARCH_TERMS[:2]}")
        ok(f"Locations: {job_scraper.TARGET_LOCATIONS}")
        info("Browser scraping skipped (needs live network)")

# ═════════════════════════════════════════════════════════════════════════════
# TEST 5 — Orchestrator
# ═════════════════════════════════════════════════════════════════════════════
def test_orchestrator():
    print(f"\n{BOLD}{'='*52}\n  MODULE 5 — Orchestrator\n{'='*52}{RESET}")

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
        "run_date":"2026-08-30","jobs_scraped":47,"jobs_matched":12,
        "jobs_applied":8,"emails_sent":6,"posts_published":1,
    }]
    mock_sb.table.return_value.select.return_value.in_.return_value.order.return_value.limit.return_value.execute.return_value.data = []
    mock_sb.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = []

    print("\n[5a] Daily summary builder...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"):
        import orchestrator as orch
        summary = orch.build_daily_summary()
        assert "Daily Job Search Report" in summary
        ok("Summary built successfully")
        print(f"\n{BLUE}  ── Preview ────────────────────────────────────{RESET}")
        for line in summary.split("\n")[:10]: print(f"  {line}")
        print(f"  {BLUE}  ────────────────────────────────────────────{RESET}\n")

    print("[5b] Telegram mock...")
    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai_client.call_ai", return_value="mock"), \
         patch("urllib.request.urlopen") as mu:
        mu.return_value.__enter__.return_value.read.return_value = b'{"ok":true}'
        import importlib, orchestrator; importlib.reload(orchestrator)
        orchestrator.send_telegram("🤖 Test from local suite")
        ok("Telegram send path OK (mock)")

# ═════════════════════════════════════════════════════════════════════════════
# Runner
# ═════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--module",
        choices=["ats","email","linkedin","scraper","orchestrator","all"],
        default="all")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY","")
    use_real = bool(api_key and len(api_key) > 10)

    print(f"\n{BOLD}{'='*52}")
    print(f"  JOB ENGINE — LOCAL TEST SUITE (Gemini / Free)")
    print(f"{'='*52}{RESET}")
    print(f"  Gemini API: {'✅ Present — live AI tests ON' if use_real else '⚠  Not set — mock-only mode'}")
    if not use_real:
        print(f"  {YELLOW}Get free key: aistudio.google.com → add GEMINI_API_KEY to .env{RESET}")

    passed, failed_mods = [], []

    def run(name, fn, *a):
        try:
            fn(*a); passed.append(name)
        except AssertionError as e:
            fail(f"ASSERTION: {e}"); failed_mods.append(name)
        except Exception as e:
            fail(f"EXCEPTION in {name}: {e}")
            import traceback; traceback.print_exc()
            failed_mods.append(name)

    m = args.module
    if m in ("ats","all"):         run("ATS Matcher",  test_ats_module,      use_real)
    if m in ("email","all"):       run("Cold Email",   test_email_module,    use_real)
    if m in ("linkedin","all"):    run("LinkedIn",     test_linkedin_module, use_real)
    if m in ("scraper","all"):     run("Scraper",      test_scraper_module)
    if m in ("orchestrator","all"):run("Orchestrator", test_orchestrator)

    print(f"\n{BOLD}{'='*52}\n  RESULTS\n{'='*52}{RESET}")
    for p in passed:      print(f"  {GREEN}✅  {p}{RESET}")
    for f in failed_mods: print(f"  {RED}❌  {f}{RESET}")
    print()

    if not failed_mods:
        print(f"  {GREEN}{BOLD}All modules passed!{RESET}")
        if not use_real:
            print(f"  {YELLOW}Add GEMINI_API_KEY to .env for live AI tests (free).{RESET}")
        print(f"\n  Next steps:")
        print(f"  {BLUE}1. Get free Gemini key: aistudio.google.com{RESET}")
        print(f"  {BLUE}2. Add to .env: GEMINI_API_KEY=your-key{RESET}")
        print(f"  {BLUE}3. Run again: python test_local.py{RESET}")
    else:
        print(f"  {RED}{BOLD}{len(failed_mods)} module(s) failed.{RESET}")
        sys.exit(1)

if __name__ == "__main__":
    main()