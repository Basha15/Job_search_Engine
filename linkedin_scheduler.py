"""
LinkedIn Post Scheduler (Gemini-powered — FREE)
"""

import os, json, logging, random
from datetime import datetime, date, timedelta, timezone
from typing import Optional
import requests
from dotenv import load_dotenv
from supabase import create_client
from ai_client import call_ai

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
AUTO_PUBLISH = os.environ.get("LINKEDIN_AUTO_PUBLISH", "false").lower() == "true"
LINKEDIN_ACCESS_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_PERSON_URN", "")

MY_CONTEXT = {
    "name": "Shaik Umar Basha",
    "role": "Python / Django Developer",
    "current_projects": [
        "AI-powered Job Search Engine (Django + Celery + PostgreSQL)",
        "REST API with JWT authentication and Redis caching",
        "Data analysis pipeline using Pandas and Matplotlib",
    ],
    "recent_learnings": [
        "Celery beat for periodic task scheduling",
        "Playwright for browser automation in Python",
        "Supabase Row Level Security policies",
    ],
    "achievements": [
        "Won Smart India Hackathon 2025",
        "Built and deployed Django REST API with 15+ endpoints",
        "Automated job application pipeline processing 50+ jobs/day",
    ],
    "hashtags": {
        "thought_leadership": ["#Python", "#SoftwareEngineering", "#BackendDevelopment", "#TechCareer", "#OpenToWork"],
        "micro_update": ["#BuildInPublic", "#100DaysOfCode", "#PythonDeveloper", "#Django", "#LearningInPublic"],
        "achievement": ["#Milestone", "#PythonDeveloper", "#SmartIndiaHackathon", "#TechIndia"],
    }
}

THOUGHT_LEADERSHIP_TOPICS = [
    "Why Django is still the best choice for rapid API development in 2025",
    "5 things I learned building a production-grade REST API as a fresher",
    "How I automated my job search with Python and Playwright",
    "What winning Smart India Hackathon taught me about real-world problem solving",
    "How to get your first dev job in India in 2025 (what actually works)",
]

def generate_thought_leadership_post(topic=None) -> dict:
    if not topic:
        topic = random.choice(THOUGHT_LEADERSHIP_TOPICS)
    hashtags = " ".join(MY_CONTEXT["hashtags"]["thought_leadership"])
    achievements = "\n".join(f"- {a}" for a in MY_CONTEXT["achievements"])

    prompt = f"""Write a LinkedIn thought-leadership post for a Python/Django developer.

AUTHOR: {MY_CONTEXT['name']} — {MY_CONTEXT['role']}, fresh grad, SIH 2025 winner
TOPIC: {topic}
MY ACHIEVEMENTS: {achievements}

REQUIREMENTS:
- Hook first line: bold statement or contrarian take that stops scrolling
- 200-280 words total
- First person, genuine, specific — no generic motivational fluff
- Include 1 real technical insight from my projects
- End with a question to drive comments
- Add line breaks between paragraphs
- Last line: {hashtags}

Write ONLY the post text, nothing else."""

    content = call_ai(prompt, max_tokens=600)
    return {"content": content, "hashtags": MY_CONTEXT["hashtags"]["thought_leadership"],
            "post_type": "thought_leadership", "generation_seed": topic}

def generate_micro_update_post(update_type="random") -> dict:
    if update_type == "random":
        update_type = random.choice(["project", "learning", "achievement"])
    if update_type == "project":
        seed = random.choice(MY_CONTEXT["current_projects"]); post_type = "micro_update"
        context = f"I'm working on: {seed}"
    elif update_type == "learning":
        seed = random.choice(MY_CONTEXT["recent_learnings"]); post_type = "learning_share"
        context = f"I just learned about: {seed}"
    else:
        seed = random.choice(MY_CONTEXT["achievements"]); post_type = "achievement"
        context = f"Recent achievement: {seed}"

    hashtags = " ".join(MY_CONTEXT["hashtags"].get(post_type, MY_CONTEXT["hashtags"]["micro_update"]))

    prompt = f"""Write a short LinkedIn micro-update post for a Python developer.

AUTHOR: {MY_CONTEXT['name']} — fresh grad, building in public
CONTEXT: {context}

REQUIREMENTS:
- 80-130 words, punchy and casual
- First person, specific — not generic
- Share ONE insight or lesson
- End with a short question or "Follow along as I build in public"
- Last line: {hashtags}
- Do NOT start with "Excited to share" or "Thrilled to announce"

Write ONLY the post text."""

    content = call_ai(prompt, max_tokens=300)
    return {"content": content, "hashtags": MY_CONTEXT["hashtags"].get(post_type, []),
            "post_type": post_type, "generation_seed": seed}

def schedule_post(post_data: dict, publish_at: datetime, requires_review=True) -> str:
    res = supabase.table("linkedin_posts").insert({
        "content": post_data["content"], "hashtags": post_data["hashtags"],
        "post_type": post_data["post_type"],
        "status": "pending_review" if requires_review else "scheduled",
        "scheduled_for": publish_at.isoformat(),
        "ai_model": "gemini-1.5-flash",
        "generation_seed": post_data["generation_seed"],
        "requires_review": requires_review,
    }).execute()
    post_id = res.data[0]["id"] if res.data else None
    log.info(f"[APPLY] Scheduled post ({post_data['post_type']}) for {publish_at.strftime('%a %b %d %H:%M')}")
    return post_id

def get_schedule_for_week(base_date=None) -> list:
    if base_date is None:
        base_date = date.today()
    tz_offset = timedelta(hours=5, minutes=30)
    schedule = []
    for i in range(7):
        d = base_date + timedelta(days=i)
        weekday = d.weekday()
        if weekday == 6:
            schedule.append((datetime(d.year, d.month, d.day, 20, 0) - tz_offset, "thought_leadership"))
        elif weekday in [0, 2, 4]:
            schedule.append((datetime(d.year, d.month, d.day, 9, 0) - tz_offset, "micro_project"))
        elif weekday in [1, 3]:
            schedule.append((datetime(d.year, d.month, d.day, 12, 0) - tz_offset, "micro_learning"))
    return schedule

def publish_to_linkedin(post_id: str, content: str) -> bool:
    if not LINKEDIN_ACCESS_TOKEN or not LINKEDIN_PERSON_URN:
        log.warning("LinkedIn credentials not set")
        return False
    headers = {"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
               "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"}
    payload = {"author": LINKEDIN_PERSON_URN, "lifecycleState": "PUBLISHED",
               "specificContent": {"com.linkedin.ugc.ShareContent": {
                   "shareCommentary": {"text": content}, "shareMediaCategory": "NONE"}},
               "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}}
    try:
        resp = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        supabase.table("linkedin_posts").update({
            "status": "published", "published_at": datetime.now(timezone.utc).isoformat(),
            "linkedin_post_id": resp.headers.get("x-linkedin-id", "unknown"),
        }).eq("id", post_id).execute()
        log.info(f"[OK] Published to LinkedIn")
        return True
    except Exception as e:
        log.error(f"LinkedIn publish failed: {e}")
        return False

def publish_due_posts():
    now = datetime.now(timezone.utc).isoformat()
    due = supabase.table("linkedin_posts").select("*").in_("status", ["scheduled"]).lte("scheduled_for", now).execute()
    count = sum(1 for post in (due.data or []) if publish_to_linkedin(post["id"], post["content"]))
    log.info(f"Published {count} due posts")
    return count

def run_weekly_content_generation(dry_run=False):
    log.info("[TARGET] Generating weekly LinkedIn content...")
    schedule = get_schedule_for_week()
    generated = []
    for publish_time, content_type in schedule:
        post_data = generate_thought_leadership_post() if content_type == "thought_leadership" else \
                    generate_micro_update_post("project" if content_type == "micro_project" else "learning")
        if not dry_run:
            post_id = schedule_post(post_data, publish_time, requires_review=not AUTO_PUBLISH)
            generated.append({"id": post_id, "type": content_type,
                             "scheduled_for": publish_time.isoformat(),
                             "preview": post_data["content"][:120] + "..."})
        else:
            log.info(f"[DRY RUN] {content_type}: {post_data['content'][:100]}...")
    log.info(f"[OK] Queued {len(generated)} posts")
    return generated

def run_daily_publisher():
    if AUTO_PUBLISH:
        supabase.table("linkedin_posts").update({"status": "scheduled"}).eq("status", "pending_review").execute()
    count = publish_due_posts()
    supabase.table("daily_run_logs").upsert({"run_date": date.today().isoformat(), "posts_published": count}, on_conflict="run_date").execute()
    return count

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["generate_week", "publish_due", "preview"], default="preview")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.action == "generate_week":
        print(json.dumps(run_weekly_content_generation(dry_run=args.dry_run), indent=2, default=str))
    elif args.action == "publish_due":
        print(f"Published {run_daily_publisher()} posts")
    elif args.action == "preview":
        tl = generate_thought_leadership_post()
        micro = generate_micro_update_post("project")
        print("=== THOUGHT LEADERSHIP ===\n"); print(tl["content"])
        print("\n=== MICRO UPDATE ===\n"); print(micro["content"])