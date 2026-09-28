"""
ATS Keyword Extractor & Resume Matcher (Gemini-powered — FREE)
"""

import os, re, json, hashlib
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client
from ai_client import call_ai, call_ai_json

load_dotenv()
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
BASE_RESUME_PATH = os.environ.get("BASE_RESUME_PATH", "resume_base.md")

def load_base_resume() -> str:
    with open(BASE_RESUME_PATH, "r") as f:
        return f.read()

def extract_jd_keywords(jd_text: str) -> dict:
    prompt = f"""You are an ATS expert. Analyze this job description and extract keywords.

Job Description:
{jd_text}

Return ONLY valid JSON with this exact structure (no markdown, no explanation):
{{
  "title": "job title",
  "experience_level": "entry",
  "min_years": 0,
  "hard_skills": ["Python", "Django"],
  "soft_skills": ["communication"],
  "tools": ["Git", "Docker"],
  "role_keywords": ["backend developer", "REST API"],
  "certifications": [],
  "responsibilities": ["build APIs"],
  "company_values": ["agile"]
}}"""
    return call_ai_json(prompt, max_tokens=1000)

def compute_ats_score(resume_text: str, jd_keywords: dict) -> dict:
    resume_lower = resume_text.lower()
    all_keywords = (
        jd_keywords.get("hard_skills", []) +
        jd_keywords.get("tools", []) +
        jd_keywords.get("role_keywords", [])
    )
    matched, missing = [], []
    for kw in all_keywords:
        if re.compile(re.escape(kw.lower()), re.IGNORECASE).search(resume_lower):
            matched.append(kw)
        else:
            missing.append(kw)

    total = len(all_keywords)
    score = round((len(matched) / total) * 100, 1) if total > 0 else 0.0
    hard_skills = jd_keywords.get("hard_skills", [])
    hard_matched = [k for k in hard_skills if k in matched]
    hard_score = (len(hard_matched) / len(hard_skills) * 100) if hard_skills else 0
    blended = round(0.6 * hard_score + 0.4 * score, 1)

    return {
        "score": blended,
        "matched_keywords": matched,
        "missing_keywords": missing,
        "matched_count": len(matched),
        "total_keywords": total,
        "hard_skill_match_pct": round(hard_score, 1)
    }

def generate_tailored_resume(base_resume, jd_text, jd_keywords, missing_keywords, job_title, company) -> str:
    missing_str = ", ".join(missing_keywords[:15])
    prompt = f"""You are an expert ATS resume writer.
Rewrite this resume to maximize ATS match for: {job_title} at {company}

MISSING KEYWORDS TO ADD NATURALLY: {missing_str}
REQUIRED SKILLS: {', '.join(jd_keywords.get('hard_skills', [])[:10])}

BASE RESUME:
{base_resume}

RULES:
1. Do NOT fabricate any experience, company, or achievement
2. Rephrase bullets to include missing keywords where truthfully applicable
3. Add a Skills section at the top with all technical skills
4. Use clean single-column format, no tables
5. Start bullets with strong action verbs
6. Format: Pure Markdown only

Output ONLY the resume Markdown, no explanations."""
    return call_ai(prompt, max_tokens=2000)

def process_job_for_ats(job_id: str, jd_text: str, job_title: str, company: str) -> dict:
    print(f"\n[SEARCH] ATS Processing: {job_title} @ {company}")
    base_resume = load_base_resume()
    jd_keywords = extract_jd_keywords(jd_text)
    match_result = compute_ats_score(base_resume, jd_keywords)
    score = match_result["score"]
    print(f"  Score: {score}/100 | Matched: {match_result['matched_count']}/{match_result['total_keywords']}")

    tailored_resume_md = None
    resume_version_tag = None

    if score >= 60:
        tailored_resume_md = generate_tailored_resume(
            base_resume, jd_text, jd_keywords,
            match_result["missing_keywords"], job_title, company
        )
        slug = re.sub(r"[^a-z0-9]+", "-", f"{job_title}-{company}".lower())[:40]
        hash_suffix = hashlib.md5(jd_text.encode()).hexdigest()[:6]
        resume_version_tag = f"v-{slug}-{hash_suffix}"
        supabase.table("resume_versions").upsert({
            "version_tag": resume_version_tag,
            "target_role": job_title,
            "target_keywords": jd_keywords.get("hard_skills", []),
            "content_md": tailored_resume_md,
        }).execute()

    update_data = {
        "ats_score": score,
        "matched_keywords": match_result["matched_keywords"],
        "missing_skills": match_result["missing_keywords"][:20],
        "required_skills": jd_keywords.get("hard_skills", []),
        "keywords": jd_keywords.get("role_keywords", []),
        "status": "matched" if score >= 60 else "scraped"
    }
    supabase.table("jobs").update(update_data).eq("id", job_id).execute()

    return {
        "job_id": job_id, "score": score,
        "matched_keywords": match_result["matched_keywords"],
        "missing_keywords": match_result["missing_keywords"],
        "tailored_resume_md": tailored_resume_md,
        "resume_version_tag": resume_version_tag,
        "qualifies": score >= 60
    }