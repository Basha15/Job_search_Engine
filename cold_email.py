"""
Cold Email Generator (Gemini-powered — FREE)
"""

import os, json, smtplib, logging
from datetime import datetime, date, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client
from ai_client import call_ai, call_ai_json

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

DAILY_EMAIL_LIMIT = 10
SENDER_NAME = os.environ.get("SENDER_NAME", "Shaik Umar Basha")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "your@email.com")

MY_PROFILE = {
    "name": "Shaik Umar Basha",
    "role": "Python / Django Backend Developer",
    "education": "B.Tech IT, Malla Reddy College of Engineering (CGPA 7.9, 2026)",
    "key_achievements": [
        "Won Smart India Hackathon (SIH) 2025",
        "Built AI-powered Job Tracker with Django REST + PostgreSQL",
        "Developed Django REST APIs with JWT auth, Celery task queues, Redis caching",
        "Created data analysis dashboards using Python, Pandas, and Matplotlib",
    ],
    "core_skills": "Python, Django, REST APIs, PostgreSQL, Celery, Redis, Git, SQL",
    "github": os.environ.get("GITHUB_URL", "https://github.com/yourusername"),
    "linkedin": os.environ.get("LINKEDIN_URL", "https://linkedin.com/in/yourusername"),
}

def get_todays_email_count() -> int:
    today = date.today().isoformat()
    res = supabase.table("outreach_logs") \
        .select("id", count="exact") \
        .eq("status", "sent") \
        .gte("sent_at", f"{today}T00:00:00") \
        .execute()
    return res.count or 0

def get_outreach_candidates(limit: int = 15) -> list:
    res = supabase.table("jobs") \
        .select("id, title, company, company_domain, location, description_raw, ats_score, apply_url, matched_keywords") \
        .in_("status", ["matched", "auto_applied"]) \
        .gte("ats_score", 70) \
        .order("ats_score", desc=True) \
        .limit(limit) \
        .execute()
    return res.data or []

def find_or_create_recruiter(company: str, company_domain: str, job_id: str) -> Optional[dict]:
    res = supabase.table("recruiters").select("*").eq("company", company).eq("is_active", True).limit(1).execute()
    if res.data:
        return res.data[0]
    generic_email = f"careers@{company_domain}" if company_domain else None
    if not generic_email:
        return None
    res = supabase.table("recruiters").upsert({
        "name": "Hiring Team",
        "email": generic_email,
        "email_verified": False,
        "company": company,
        "company_domain": company_domain,
        "role_title": "HR / Talent Acquisition",
        "source_job_id": job_id,
        "discovery_method": "generic_careers",
    }, on_conflict="email").execute()
    return res.data[0] if res.data else None

def generate_cold_email(recruiter: dict, job: dict) -> dict:
    matched_kw = ", ".join((job.get("matched_keywords") or [])[:6])
    achievements = "\n".join(f"- {a}" for a in MY_PROFILE["key_achievements"])

    prompt = f"""Write a cold outreach email from a job seeker to a recruiter.

RECRUITER: {recruiter['name']} ({recruiter.get('role_title','Recruiter')}) at {recruiter['company']}
ROLE: {job['title']} | Location: {job.get('location','India')}
SKILLS THEY WANT: {matched_kw}

CANDIDATE:
- Name: {MY_PROFILE['name']}
- Role: {MY_PROFILE['role']}
- Education: {MY_PROFILE['education']}
- Skills: {MY_PROFILE['core_skills']}
- Achievements:
{achievements}
- GitHub: {MY_PROFILE['github']}
- LinkedIn: {MY_PROFILE['linkedin']}

Write a confident, warm, specific email. NO generic openers like "I hope this finds you well".
Max 220 words. End with a clear CTA.

Return ONLY valid JSON (no markdown):
{{
  "subject": "...",
  "body_text": "plain text email",
  "body_html": "<p>html version</p>"
}}"""

    return call_ai_json(prompt, max_tokens=1000)

def send_via_gmail(to_email, to_name, subject, body_html, body_text) -> str:
    smtp_user = os.environ["GMAIL_USER"]
    smtp_pass = os.environ["GMAIL_APP_PASSWORD"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SENDER_NAME} <{smtp_user}>"
    msg["To"] = f"{to_name} <{to_email}>"
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo(); server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
    return "sent"

def log_outreach(recruiter_id, job_id, subject, body_text, body_html, status, message_id=None, sent_via="gmail"):
    supabase.table("outreach_logs").insert({
        "recruiter_id": recruiter_id, "job_id": job_id,
        "subject": subject, "body_text": body_text, "body_html": body_html,
        "status": status, "sent_via": sent_via, "message_id": message_id,
        "sent_at": datetime.now(timezone.utc).isoformat() if status == "sent" else None,
    }).execute()

def run_daily_outreach(send_method="gmail", dry_run=False):
    already_sent = get_todays_email_count()
    remaining = DAILY_EMAIL_LIMIT - already_sent
    if remaining <= 0:
        log.info("Daily email limit reached.")
        return []

    jobs = get_outreach_candidates(limit=remaining + 5)
    sent_count, results = 0, []

    for job in jobs:
        if sent_count >= remaining:
            break
        company = job["company"]
        company_domain = job.get("company_domain") or company.lower().replace(" ", "") + ".com"
        recruiter = find_or_create_recruiter(company, company_domain, job["id"])
        if not recruiter or not recruiter.get("email"):
            continue

        today = date.today().isoformat()
        existing = supabase.table("outreach_logs").select("id").eq("recruiter_id", recruiter["id"]).gte("created_at", f"{today}T00:00:00").execute()
        if existing.data:
            continue

        try:
            email_content = generate_cold_email(recruiter, job)
            subject, body_text, body_html = email_content["subject"], email_content["body_text"], email_content["body_html"]

            if dry_run:
                log.info(f"[DRY RUN] To: {recruiter['email']} | Subject: {subject}")
                log_outreach(recruiter["id"], job["id"], subject, body_text, body_html, status="queued")
                results.append({"company": company, "status": "dry_run", "subject": subject})
                sent_count += 1
                continue

            send_via_gmail(recruiter["email"], recruiter["name"], subject, body_html, body_text)
            log_outreach(recruiter["id"], job["id"], subject, body_text, body_html, status="sent", sent_via="gmail")
            log.info(f"[OK] Sent to {recruiter['name']} @ {company}")
            results.append({"company": company, "recruiter": recruiter["name"], "status": "sent"})
            sent_count += 1
        except Exception as e:
            log.error(f"Failed for {company}: {e}")

    log.info(f"[MAIL] Outreach done: {sent_count} emails sent")
    return results

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    results = run_daily_outreach(dry_run=args.dry_run)
    print(json.dumps(results, indent=2))