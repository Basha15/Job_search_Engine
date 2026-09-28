-- ============================================================
-- JOB SEARCH & PERSONAL BRANDING ENGINE — DATABASE SCHEMA
-- Platform: Supabase / PostgreSQL
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- for fuzzy text search

-- ============================================================
-- ENUM TYPES
-- ============================================================

CREATE TYPE job_status AS ENUM (
  'scraped',       -- raw, unfiltered
  'matched',       -- passed ATS score threshold
  'saved',         -- user bookmarked
  'auto_applied',  -- system applied
  'manual_applied',-- user applied manually
  'interviewing',
  'offered',
  'rejected',
  'withdrawn'
);

CREATE TYPE platform AS ENUM (
  'naukri', 'linkedin', 'unstop', 'ycombinator',
  'lever', 'greenhouse', 'workday', 'company_direct', 'other'
);

CREATE TYPE outreach_status AS ENUM (
  'queued', 'sent', 'opened', 'replied', 'bounced', 'failed'
);

CREATE TYPE post_status AS ENUM (
  'draft', 'pending_review', 'scheduled', 'published', 'failed'
);

CREATE TYPE post_type AS ENUM (
  'thought_leadership', 'micro_update', 'project_milestone',
  'learning_share', 'achievement'
);

-- ============================================================
-- TABLE: jobs
-- ============================================================

CREATE TABLE jobs (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- Source info
  platform          platform NOT NULL,
  external_id       TEXT,                    -- platform's own job ID
  job_url           TEXT NOT NULL,
  apply_url         TEXT,
  
  -- Job details
  title             TEXT NOT NULL,
  company           TEXT NOT NULL,
  company_domain    TEXT,
  location          TEXT,
  is_remote         BOOLEAN DEFAULT FALSE,
  employment_type   TEXT,                    -- full-time, contract, etc.
  experience_level  TEXT,                    -- entry, mid, senior
  min_experience    INT,                     -- years
  max_experience    INT,
  salary_min        NUMERIC,
  salary_max        NUMERIC,
  salary_currency   TEXT DEFAULT 'INR',
  
  -- Content
  description_raw   TEXT NOT NULL,
  description_clean TEXT,
  required_skills   TEXT[],                  -- extracted array
  preferred_skills  TEXT[],
  keywords          TEXT[],
  
  -- ATS matching
  ats_score         NUMERIC(5,2),            -- 0-100 match score
  missing_skills    TEXT[],
  matched_keywords  TEXT[],
  
  -- Lifecycle
  status            job_status DEFAULT 'scraped',
  posted_at         TIMESTAMPTZ,
  scraped_at        TIMESTAMPTZ DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW(),
  
  -- Dedup guard
  UNIQUE(platform, external_id),
  UNIQUE(job_url)
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_ats_score ON jobs(ats_score DESC);
CREATE INDEX idx_jobs_scraped_at ON jobs(scraped_at DESC);
CREATE INDEX idx_jobs_platform ON jobs(platform);
CREATE INDEX idx_jobs_company ON jobs USING gin(company gin_trgm_ops);
CREATE INDEX idx_jobs_title ON jobs USING gin(title gin_trgm_ops);
CREATE INDEX idx_jobs_skills ON jobs USING gin(required_skills);

-- ============================================================
-- TABLE: applications
-- ============================================================

CREATE TABLE applications (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  job_id            UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  
  -- Resume used
  resume_version    TEXT,                    -- e.g., "v1.2-django-focused"
  resume_url        TEXT,                    -- link to tailored PDF/MD
  cover_letter      TEXT,
  
  -- Application metadata
  applied_at        TIMESTAMPTZ DEFAULT NOW(),
  applied_via       TEXT,                    -- 'auto' | 'manual' | 'easy_apply'
  confirmation_id   TEXT,                    -- application ref number if any
  
  -- Status tracking
  status            job_status DEFAULT 'auto_applied',
  status_updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Interview pipeline
  interview_round   INT DEFAULT 0,
  interview_notes   TEXT,
  offer_details     JSONB,                   -- salary, joining date, etc.
  
  -- Follow-up
  last_followup_at  TIMESTAMPTZ,
  followup_count    INT DEFAULT 0,
  
  notes             TEXT,
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_applications_job_id ON applications(job_id);
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_applications_applied_at ON applications(applied_at DESC);

-- ============================================================
-- TABLE: recruiters
-- ============================================================

CREATE TABLE recruiters (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- Identity
  name              TEXT NOT NULL,
  email             TEXT,
  email_verified    BOOLEAN DEFAULT FALSE,
  linkedin_url      TEXT,
  linkedin_id       TEXT,
  
  -- Company context
  company           TEXT,
  company_domain    TEXT,
  role_title        TEXT,                    -- "Technical Recruiter", "HR Manager"
  
  -- Discovered via
  source_job_id     UUID REFERENCES jobs(id),
  discovery_method  TEXT,                    -- 'linkedin_scrape' | 'job_posting' | 'manual'
  
  -- Contact quality
  is_active         BOOLEAN DEFAULT TRUE,
  response_rate     NUMERIC(5,2),
  last_seen_at      TIMESTAMPTZ,
  
  -- CRM
  notes             TEXT,
  tags              TEXT[],
  
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW(),
  
  UNIQUE(email),
  UNIQUE(linkedin_id)
);

CREATE INDEX idx_recruiters_company ON recruiters(company);
CREATE INDEX idx_recruiters_email ON recruiters(email);

-- ============================================================
-- TABLE: outreach_logs
-- ============================================================

CREATE TABLE outreach_logs (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  recruiter_id      UUID NOT NULL REFERENCES recruiters(id) ON DELETE CASCADE,
  job_id            UUID REFERENCES jobs(id),
  
  -- Email content
  subject           TEXT NOT NULL,
  body_text         TEXT NOT NULL,
  body_html         TEXT,
  
  -- Delivery
  status            outreach_status DEFAULT 'queued',
  sent_via          TEXT,                    -- 'gmail_smtp' | 'resend'
  message_id        TEXT,                    -- SMTP/API message ID for tracking
  
  -- Tracking
  sent_at           TIMESTAMPTZ,
  opened_at         TIMESTAMPTZ,
  replied_at        TIMESTAMPTZ,
  reply_snippet     TEXT,
  bounce_reason     TEXT,
  
  -- Sequence position (for follow-ups)
  sequence_step     INT DEFAULT 1,          -- 1 = initial, 2 = follow-up, etc.
  parent_id         UUID REFERENCES outreach_logs(id),
  
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_outreach_recruiter ON outreach_logs(recruiter_id);
CREATE INDEX idx_outreach_job ON outreach_logs(job_id);
CREATE INDEX idx_outreach_status ON outreach_logs(status);
CREATE INDEX idx_outreach_sent_at ON outreach_logs(sent_at DESC);

-- ============================================================
-- TABLE: linkedin_posts
-- ============================================================

CREATE TABLE linkedin_posts (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- Content
  content           TEXT NOT NULL,
  media_urls        TEXT[],
  hashtags          TEXT[],
  post_type         post_type NOT NULL,
  
  -- Scheduling
  status            post_status DEFAULT 'draft',
  scheduled_for     TIMESTAMPTZ,
  published_at      TIMESTAMPTZ,
  linkedin_post_id  TEXT,                    -- returned by LinkedIn API after publish
  
  -- Generation metadata
  ai_prompt_used    TEXT,
  ai_model          TEXT DEFAULT 'claude-sonnet-4-6',
  generation_seed   TEXT,                    -- context used: project, milestone, etc.
  
  -- Performance (fetched via LinkedIn API later)
  impressions       INT DEFAULT 0,
  reactions         INT DEFAULT 0,
  comments          INT DEFAULT 0,
  shares            INT DEFAULT 0,
  
  -- Approval
  requires_review   BOOLEAN DEFAULT TRUE,
  reviewed_by       TEXT,
  reviewed_at       TIMESTAMPTZ,
  review_notes      TEXT,
  
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_posts_status ON linkedin_posts(status);
CREATE INDEX idx_posts_scheduled ON linkedin_posts(scheduled_for);
CREATE INDEX idx_posts_type ON linkedin_posts(post_type);

-- ============================================================
-- TABLE: daily_run_logs
-- ============================================================

CREATE TABLE daily_run_logs (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_date          DATE NOT NULL UNIQUE,
  
  -- Scraping stats
  jobs_scraped      INT DEFAULT 0,
  jobs_matched      INT DEFAULT 0,
  jobs_applied      INT DEFAULT 0,
  
  -- Outreach stats
  emails_sent       INT DEFAULT 0,
  emails_queued     INT DEFAULT 0,
  
  -- LinkedIn stats
  posts_published   INT DEFAULT 0,
  posts_queued      INT DEFAULT 0,
  
  -- Errors
  errors            JSONB DEFAULT '[]',
  
  -- Notification
  summary_sent_at   TIMESTAMPTZ,
  summary_channel   TEXT,                    -- 'telegram' | 'email'
  
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLE: resume_versions
-- ============================================================

CREATE TABLE resume_versions (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  version_tag       TEXT NOT NULL UNIQUE,   -- e.g., "v1.2-django-backend"
  target_role       TEXT,
  target_keywords   TEXT[],
  
  content_md        TEXT NOT NULL,           -- Markdown source
  pdf_url           TEXT,                    -- hosted PDF
  
  ats_template      TEXT DEFAULT 'single_column',
  
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  is_active         BOOLEAN DEFAULT TRUE
);

-- ============================================================
-- VIEWS
-- ============================================================

-- Dashboard: application pipeline summary
CREATE OR REPLACE VIEW v_pipeline_summary AS
SELECT
  j.status,
  COUNT(*) AS count,
  ROUND(AVG(j.ats_score), 1) AS avg_ats_score,
  MAX(a.applied_at) AS latest_activity
FROM jobs j
LEFT JOIN applications a ON a.job_id = j.id
WHERE j.status NOT IN ('scraped', 'matched')
GROUP BY j.status;

-- Top matched jobs not yet applied
CREATE OR REPLACE VIEW v_top_matches AS
SELECT
  j.id, j.title, j.company, j.location, j.is_remote,
  j.ats_score, j.platform, j.apply_url,
  j.posted_at, j.required_skills
FROM jobs j
WHERE j.status = 'matched'
  AND j.ats_score >= 70
ORDER BY j.ats_score DESC, j.posted_at DESC
LIMIT 50;

-- Today's outreach summary
CREATE OR REPLACE VIEW v_todays_outreach AS
SELECT
  o.id, o.subject, o.status, o.sent_at,
  r.name AS recruiter_name, r.email,
  r.company, r.role_title,
  j.title AS job_title, j.apply_url
FROM outreach_logs o
JOIN recruiters r ON r.id = o.recruiter_id
LEFT JOIN jobs j ON j.id = o.job_id
WHERE DATE(o.sent_at) = CURRENT_DATE OR DATE(o.created_at) = CURRENT_DATE
ORDER BY o.created_at DESC;

-- ============================================================
-- ROW LEVEL SECURITY (Supabase)
-- ============================================================

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE recruiters ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE linkedin_posts ENABLE ROW LEVEL SECURITY;

-- Service role bypass (for backend automation)
CREATE POLICY "service_role_all" ON jobs FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON applications FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON recruiters FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON outreach_logs FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON linkedin_posts FOR ALL USING (auth.role() = 'service_role');
