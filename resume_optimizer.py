"""
Resume Optimizer — Auto-tailors your resume for each matched job
────────────────────────────────────────────────────────────────
Workflow:
  1. Pulls top matched jobs from Supabase (ATS score >= 50)
  2. For each job, generates a fully tailored resume using Gemini AI
  3. Saves tailored resume as Markdown to Supabase resume_versions table
  4. Also saves local .md files in a resumes/ folder for easy access
  5. Shows a summary of all generated resumes with ATS scores

Usage:
    python resume_optimizer.py               # optimize top 5 jobs
    python resume_optimizer.py --limit 10    # optimize top 10 jobs
    python resume_optimizer.py --min-score 60  # only jobs with score >= 60
    python resume_optimizer.py --preview     # show resume without saving
"""

import os
import re
import json
import hashlib
import argparse
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
from ai_client import call_ai, call_ai_json

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

BASE_RESUME_PATH = os.environ.get("BASE_RESUME_PATH", "resume_base.md")
OUTPUT_DIR = "resumes"

# ── Your full base profile for AI context ────────────────────────────────────
MY_PROFILE = {
    "name": "Shaik Umar Basha",
    "email": "shaikumarbasha19@gmail.com",
    "phone": "+91-XXXXXXXXXX",
    "location": "Hyderabad, India",
    "linkedin": "https://www.linkedin.com/in/shaik-umar-basha-28b07b320/",
    "github": "https://github.com/Basha15",
    "education": "B.Tech Information Technology, Malla Reddy College of Engineering, Hyderabad (CGPA: 7.9, 2026)",
    "achievements": [
        "Won Smart India Hackathon (SIH) 2025 — National level government competition",
        "Built AI-powered Job Tracker with Django REST + PostgreSQL",
        "Developed Django REST APIs with JWT auth, Celery task queues, Redis caching",
        "Created data analysis dashboards using Python, Pandas, Matplotlib",
        "Automated job application pipeline processing 50+ jobs/day using Playwright",
    ],
    "skills": {
        "languages": ["Python", "SQL", "JavaScript", "HTML", "CSS"],
        "frameworks": ["Django", "Django REST Framework", "FastAPI", "React (basic)"],
        "databases": ["PostgreSQL", "MySQL", "SQLite", "Supabase"],
        "tools": ["Git", "GitHub", "Docker (basic)", "Linux", "Postman", "VS Code"],
        "libraries": ["Pandas", "Matplotlib", "NumPy", "Celery", "Redis", "Playwright"],
        "concepts": ["REST APIs", "JWT Authentication", "Async Tasks", "ORM", "MVC", "Agile"],
    },
    "experience": [
        {
            "role": "Backend Developer Intern",
            "company": "TechStartup",
            "location": "Hyderabad",
            "duration": "Jan 2026 – May 2026",
            "bullets": [
                "Built 15+ Django REST API endpoints with JWT authentication and role-based access control",
                "Implemented Celery + Redis for async task processing, reducing response latency by 40%",
                "Designed PostgreSQL schemas with optimized indexes for a job-tracking application",
                "Wrote unit tests using pytest achieving 85% code coverage",
                "Collaborated with frontend team using Git branching and code reviews",
            ]
        }
    ],
    "projects": [
        {
            "name": "AI-Powered Job Search Engine",
            "tech": "Python, Django, Playwright, PostgreSQL, Gemini AI, Supabase",
            "bullets": [
                "Built autonomous pipeline scraping 50+ jobs/day from Naukri, LinkedIn, YC",
                "Implemented ATS keyword matching scoring system with 0-100 accuracy",
                "Automated cold email generation using Gemini AI for recruiter outreach",
                "Deployed REST API with Supabase backend and real-time dashboard",
            ]
        },
        {
            "name": "Smart India Hackathon 2025 — Winner",
            "tech": "Django, WebSockets, PostgreSQL, React",
            "bullets": [
                "Built real-time public grievance portal serving 1000+ concurrent users",
                "Implemented WebSocket-based live notifications reducing response time by 60%",
                "Won national-level competition against 500+ teams across India",
            ]
        },
        {
            "name": "Data Analysis Dashboard",
            "tech": "Python, Pandas, Matplotlib, SQL",
            "bullets": [
                "Analyzed datasets of 100K+ records using Pandas for business insights",
                "Built interactive visualizations with Matplotlib revealing key trends",
                "Automated report generation saving 5+ hours of manual work per week",
            ]
        }
    ]
}


# ── Load base resume ──────────────────────────────────────────────────────────
def load_base_resume() -> str:
    try:
        with open(BASE_RESUME_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        log.warning(f"resume_base.md not found — using profile data instead")
        return build_resume_from_profile(MY_PROFILE)


def build_resume_from_profile(profile: dict) -> str:
    """Build a base resume string from MY_PROFILE dict."""
    skills_flat = []
    for category, items in profile["skills"].items():
        skills_flat.extend(items)

    exp_text = ""
    for e in profile["experience"]:
        bullets = "\n".join(f"- {b}" for b in e["bullets"])
        exp_text += f"\n**{e['role']}** — {e['company']}, {e['location']} ({e['duration']})\n{bullets}\n"

    proj_text = ""
    for p in profile["projects"]:
        bullets = "\n".join(f"- {b}" for b in p["bullets"])
        proj_text += f"\n**{p['name']}** ({p['tech']})\n{bullets}\n"

    return f"""# {profile['name']}
{profile['location']} | {profile['email']} | {profile['github']} | {profile['linkedin']}

## Skills
{', '.join(skills_flat)}

## Experience
{exp_text}

## Projects
{proj_text}

## Education
{profile['education']}

## Achievements
{chr(10).join(f"- {a}" for a in profile['achievements'])}
"""


# ── Pull top matched jobs ─────────────────────────────────────────────────────
def get_jobs_to_optimize(limit: int = 5, min_score: float = 50) -> list:
    """Fetch top jobs from Supabase that need resume optimization."""
    res = supabase.table("jobs") \
        .select("id, title, company, location, is_remote, ats_score, description_raw, apply_url, platform, required_skills, missing_skills, matched_keywords") \
        .in_("status", ["matched", "scraped"]) \
        .gte("ats_score", min_score) \
        .order("ats_score", desc=True) \
        .limit(limit) \
        .execute()

    return res.data or []


# ── Core: Generate tailored resume ───────────────────────────────────────────
def generate_tailored_resume(job: dict, base_resume: str) -> dict:
    """
    Uses Gemini AI to generate a tailored ATS-optimized resume for a specific job.
    Returns dict with resume_md, new_score_estimate, key_changes.
    """
    job_title = job.get("title", "Software Developer")
    company = job.get("company", "Company")
    jd = job.get("description_raw", "")[:3000]  # limit JD length
    required_skills = job.get("required_skills") or []
    missing_skills = job.get("missing_skills") or []
    matched_keywords = job.get("matched_keywords") or []
    current_score = job.get("ats_score", 0)

    missing_str = ", ".join(missing_skills[:12]) if missing_skills else "none identified"
    required_str = ", ".join(required_skills[:12]) if required_skills else "see JD"
    matched_str = ", ".join(matched_keywords[:8]) if matched_keywords else "none"

    prompt = f"""You are an expert ATS resume writer helping a fresh graduate get hired.

TARGET JOB: {job_title} at {company}
CURRENT ATS SCORE: {current_score}/100
LOCATION: {job.get('location', 'India')} {'(Remote)' if job.get('is_remote') else ''}

REQUIRED SKILLS FROM JD: {required_str}
SKILLS I ALREADY MATCHED: {matched_str}
SKILLS I AM MISSING: {missing_str}

JOB DESCRIPTION:
{jd}

MY BASE RESUME:
{base_resume}

YOUR TASK:
Rewrite the resume to maximize ATS score for THIS specific job.

STRICT RULES:
1. NEVER fabricate experience, companies, degrees, or achievements not in base resume
2. DO rephrase existing bullets to naturally include missing keywords where applicable
3. DO add a tailored Skills section at the very top with ALL matched + required skills
4. DO add a 2-line Professional Summary targeting this exact role and company
5. DO use single-column clean format — no tables, no columns, no graphics
6. DO start every bullet with a strong action verb (Built, Developed, Designed, etc.)
7. DO use numbers and metrics from the base resume — never invent new ones
8. DO reorder sections: Summary -> Skills -> Experience -> Projects -> Education
9. DO include all keywords naturally — ATS scanners look for exact matches
10. FORMAT: Pure Markdown only, h1 for name, h2 for sections

OUTPUT FORMAT — Return JSON only:
{{
  "resume_md": "full markdown resume here",
  "key_changes": ["change 1", "change 2", "change 3"],
  "estimated_ats_score": 85,
  "targeted_keywords": ["keyword1", "keyword2"]
}}"""

    result = call_ai_json(prompt, max_tokens=3000)
    return result


# ── Save resume to file and Supabase ─────────────────────────────────────────
def save_resume(job: dict, resume_data: dict) -> str:
    """Save tailored resume to local file and Supabase."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Create filename
    slug = re.sub(r"[^a-z0-9]+", "_", f"{job['title']}_{job['company']}".lower())[:50]
    hash_suffix = hashlib.md5(job["id"].encode()).hexdigest()[:6]
    filename = f"{slug}_{hash_suffix}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)
    version_tag = f"v-{slug}-{hash_suffix}"

    resume_md = resume_data.get("resume_md", "")

    # Save locally
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(resume_md)

    # Save to Supabase
    try:
        supabase.table("resume_versions").upsert({
            "version_tag": version_tag,
            "target_role": job["title"],
            "target_keywords": resume_data.get("targeted_keywords", []),
            "content_md": resume_md,
            "is_active": True,
        }, on_conflict="version_tag").execute()

        # Update job with resume version tag
        supabase.table("jobs").update({
            "status": "matched",
            "ats_score": resume_data.get("estimated_ats_score", job.get("ats_score", 0))
        }).eq("id", job["id"]).execute()

    except Exception as e:
        log.warning(f"Could not save to Supabase: {e}")

    return filepath


# ── Print resume summary ──────────────────────────────────────────────────────
def print_summary(job: dict, resume_data: dict, filepath: str):
    print(f"\n{'='*60}")
    print(f"  Job: {job['title']} @ {job['company']}")
    print(f"  Location: {job.get('location','India')} {'(Remote)' if job.get('is_remote') else ''}")
    print(f"  Platform: {job.get('platform','').upper()}")
    print(f"  Apply: {job.get('apply_url','N/A')}")
    print(f"  ATS Score: {job.get('ats_score',0):.0f} -> {resume_data.get('estimated_ats_score','?')}/100 (estimated)")
    print(f"  Saved: {filepath}")
    print(f"\n  Key changes made:")
    for change in resume_data.get("key_changes", [])[:5]:
        print(f"    - {change}")
    print(f"\n  Keywords targeted:")
    print(f"    {', '.join(resume_data.get('targeted_keywords',[])[:8])}")
    print(f"{'='*60}")


# ── Main ──────────────────────────────────────────────────────────────────────
def run_resume_optimizer(limit: int = 5, min_score: float = 50, preview: bool = False):
    print(f"\n[RESUME OPTIMIZER] Starting...")
    print(f"  Fetching top {limit} jobs with ATS score >= {min_score}%\n")

    base_resume = load_base_resume()
    jobs = get_jobs_to_optimize(limit=limit, min_score=min_score)

    if not jobs:
        print(f"  No jobs found with ATS score >= {min_score}.")
        print(f"  Run the scraper first: py -3.12 orchestrator.py --run daily")
        return

    print(f"  Found {len(jobs)} jobs to optimize resumes for:\n")
    for i, job in enumerate(jobs):
        print(f"  {i+1}. [{job.get('ats_score',0):.0f}%] {job['title']} @ {job['company']}")

    print(f"\n  Generating tailored resumes (this takes ~30-60 seconds per job)...\n")

    results = []
    for i, job in enumerate(jobs):
        print(f"\n[{i+1}/{len(jobs)}] Optimizing for: {job['title']} @ {job['company']}")
        print(f"  Current ATS score: {job.get('ats_score', 0):.0f}/100")

        try:
            resume_data = generate_tailored_resume(job, base_resume)

            if preview:
                print(f"\n--- RESUME PREVIEW (first 500 chars) ---")
                print(resume_data.get("resume_md", "")[:500])
                print("--- END PREVIEW ---")
                results.append({"job": job["title"], "company": job["company"],
                                "estimated_score": resume_data.get("estimated_ats_score")})
            else:
                filepath = save_resume(job, resume_data)
                print_summary(job, resume_data, filepath)
                results.append({"job": job["title"], "company": job["company"],
                                "filepath": filepath,
                                "estimated_score": resume_data.get("estimated_ats_score")})

        except Exception as e:
            log.error(f"  Failed for {job['title']} @ {job['company']}: {e}")

    # Final summary
    print(f"\n{'='*60}")
    print(f"  OPTIMIZATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Resumes generated: {len(results)}/{len(jobs)}")
    if not preview:
        print(f"  Saved to: {os.path.abspath(OUTPUT_DIR)}/")
        print(f"\n  Next steps:")
        print(f"  1. Open the resumes/ folder")
        print(f"  2. Review each tailored resume")
        print(f"  3. Apply using the job URLs above")
    print(f"{'='*60}\n")

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resume Optimizer for Job Applications")
    parser.add_argument("--limit", type=int, default=5,
                        help="Number of jobs to optimize resumes for (default: 5)")
    parser.add_argument("--min-score", type=float, default=50,
                        help="Minimum ATS score to consider (default: 50)")
    parser.add_argument("--preview", action="store_true",
                        help="Preview resume without saving")
    args = parser.parse_args()

    run_resume_optimizer(
        limit=args.limit,
        min_score=args.min_score,
        preview=args.preview
    )