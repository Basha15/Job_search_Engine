// dashboard/JobSearchDashboard.jsx
// ─────────────────────────────────────────────────────────────────
// Job Search & Personal Branding Engine — Live Dashboard
// Stack: Next.js App Router + TailwindCSS + Shadcn UI + Lucide Icons
//
// Paste this into: app/dashboard/page.tsx  (or as a client component)
// Install: npm install lucide-react @supabase/supabase-js recharts
// ─────────────────────────────────────────────────────────────────

"use client";

import { useState, useEffect } from "react";
import {
  Briefcase, Mail, Linkedin, TrendingUp, CheckCircle2, Clock,
  AlertCircle, ChevronRight, RefreshCw, Send, Eye, Award,
  BarChart2, Zap, Target, User, ExternalLink, Search
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from "recharts";
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
);

// ── Status config ─────────────────────────────────────────────────────────────
const STATUS_CONFIG = {
  scraped:        { label: "Scraped",      color: "bg-gray-100 text-gray-700",      dot: "bg-gray-400" },
  matched:        { label: "Matched",      color: "bg-blue-100 text-blue-700",      dot: "bg-blue-500" },
  saved:          { label: "Saved",        color: "bg-purple-100 text-purple-700",   dot: "bg-purple-500" },
  auto_applied:   { label: "Auto Applied", color: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" },
  manual_applied: { label: "Applied",      color: "bg-teal-100 text-teal-700",       dot: "bg-teal-500" },
  interviewing:   { label: "Interviewing", color: "bg-amber-100 text-amber-700",     dot: "bg-amber-500" },
  offered:        { label: "Offered",      color: "bg-green-100 text-green-700",     dot: "bg-green-500" },
  rejected:       { label: "Rejected",     color: "bg-red-100 text-red-700",         dot: "bg-red-400" },
};

const ATS_COLOR = (score) => {
  if (score >= 85) return "text-emerald-600";
  if (score >= 70) return "text-blue-600";
  if (score >= 55) return "text-amber-600";
  return "text-red-500";
};

// ── Sub-components ────────────────────────────────────────────────────────────
function StatCard({ icon: Icon, label, value, sub, accent = false }) {
  return (
    <div className={`rounded-xl border p-4 flex flex-col gap-1 ${accent ? "border-blue-200 bg-blue-50" : "border-gray-200 bg-white"}`}>
      <div className="flex items-center gap-2 text-gray-500">
        <Icon size={16} />
        <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <div className={`text-2xl font-semibold ${accent ? "text-blue-700" : "text-gray-900"}`}>{value}</div>
      {sub && <div className="text-xs text-gray-400">{sub}</div>}
    </div>
  );
}

function ATSBadge({ score }) {
  if (!score) return <span className="text-gray-400 text-sm">—</span>;
  return (
    <span className={`font-semibold text-sm ${ATS_COLOR(score)}`}>
      {score.toFixed(0)}%
    </span>
  );
}

function StatusPill({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.scraped;
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${cfg.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

function PipelineBar({ pipeline }) {
  const stages = ["matched", "auto_applied", "manual_applied", "interviewing", "offered"];
  const total = stages.reduce((s, k) => s + (pipeline[k] || 0), 0) || 1;

  return (
    <div className="space-y-2">
      {stages.map((stage) => {
        const count = pipeline[stage] || 0;
        const pct = Math.round((count / total) * 100);
        const cfg = STATUS_CONFIG[stage];
        return (
          <div key={stage} className="flex items-center gap-3">
            <span className="text-xs text-gray-500 w-24 text-right">{cfg.label}</span>
            <div className="flex-1 bg-gray-100 rounded-full h-2">
              <div
                className={`h-2 rounded-full ${cfg.dot}`}
                style={{ width: `${Math.max(pct, 2)}%`, transition: "width 0.5s ease" }}
              />
            </div>
            <span className="text-xs font-medium text-gray-700 w-6">{count}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export default function JobSearchDashboard() {
  const [tab, setTab] = useState("overview");
  const [jobs, setJobs] = useState([]);
  const [outreach, setOutreach] = useState([]);
  const [posts, setPosts] = useState([]);
  const [runLogs, setRunLogs] = useState([]);
  const [pipeline, setPipeline] = useState({});
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const [search, setSearch] = useState("");

  const fetchData = async () => {
    setLoading(true);

    const [jobsRes, outreachRes, postsRes, logsRes] = await Promise.all([
      supabase.from("jobs")
        .select("id, title, company, location, is_remote, ats_score, status, platform, apply_url, posted_at, required_skills")
        .not("status", "eq", "scraped")
        .order("ats_score", { ascending: false })
        .limit(100),

      supabase.from("outreach_logs")
        .select("*, recruiters(name, company, role_title)")
        .order("created_at", { ascending: false })
        .limit(30),

      supabase.from("linkedin_posts")
        .select("id, content, post_type, status, scheduled_for, published_at, impressions, reactions")
        .order("created_at", { ascending: false })
        .limit(20),

      supabase.from("daily_run_logs")
        .select("*")
        .order("run_date", { ascending: false })
        .limit(14),
    ]);

    setJobs(jobsRes.data || []);
    setOutreach(outreachRes.data || []);
    setPosts(postsRes.data || []);
    setRunLogs(logsRes.data || []);

    // Build pipeline counts
    const pipe = {};
    (jobsRes.data || []).forEach((j) => {
      pipe[j.status] = (pipe[j.status] || 0) + 1;
    });
    setPipeline(pipe);

    setLastRefresh(new Date());
    setLoading(false);
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60 * 1000); // refresh every minute
    return () => clearInterval(interval);
  }, []);

  // Derived stats
  const totalApplied = (pipeline.auto_applied || 0) + (pipeline.manual_applied || 0);
  const totalMatched = pipeline.matched || 0;
  const interviewing = pipeline.interviewing || 0;
  const todayEmails = outreach.filter(o =>
    new Date(o.sent_at).toDateString() === new Date().toDateString()
  ).length;
  const avgATS = jobs.length
    ? (jobs.reduce((s, j) => s + (j.ats_score || 0), 0) / jobs.length).toFixed(1)
    : 0;

  // Chart data: last 14 days
  const chartData = [...runLogs].reverse().map((log) => ({
    date: new Date(log.run_date).toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
    Applied: log.jobs_applied,
    Emailed: log.emails_sent,
    Scraped: log.jobs_scraped,
  }));

  // Filtered jobs
  const filteredJobs = jobs.filter(j =>
    !search ||
    j.title?.toLowerCase().includes(search.toLowerCase()) ||
    j.company?.toLowerCase().includes(search.toLowerCase())
  );

  const TABS = [
    { id: "overview", label: "Overview", icon: BarChart2 },
    { id: "jobs", label: `Jobs (${jobs.length})`, icon: Briefcase },
    { id: "outreach", label: `Outreach (${outreach.length})`, icon: Mail },
    { id: "linkedin", label: "LinkedIn", icon: Linkedin },
  ];

  return (
    <div className="min-h-screen bg-gray-50 font-sans">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <Zap size={18} className="text-white" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-gray-900">Job Search Engine</h1>
              <p className="text-xs text-gray-400">Basha · Hyderabad</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400">
              Updated {lastRefresh.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
            </span>
            <button
              onClick={fetchData}
              disabled={loading}
              className="flex items-center gap-1.5 text-xs border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50 text-gray-600 disabled:opacity-40"
            >
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-6">

        {/* Stat cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <StatCard icon={Target} label="Matched" value={totalMatched} sub="ATS score ≥60%" accent />
          <StatCard icon={CheckCircle2} label="Applied" value={totalApplied} sub={`Today: ${runLogs[0]?.jobs_applied || 0}`} />
          <StatCard icon={Mail} label="Emails Sent" value={outreach.filter(o => o.status === "sent").length} sub={`Today: ${todayEmails}/10`} />
          <StatCard icon={TrendingUp} label="Avg ATS Score" value={`${avgATS}%`} sub="Across matched jobs" />
          <StatCard icon={User} label="Interviewing" value={interviewing} sub={interviewing > 0 ? "🔥 Active" : "Keep pushing"} />
          <StatCard icon={Award} label="Offers" value={pipeline.offered || 0} sub="Total received" />
        </div>

        {/* Tab navigation */}
        <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg font-medium transition-all ${
                tab === id
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>

        {/* ── Overview Tab ──────────────────────────────────────────────────── */}
        {tab === "overview" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Activity chart */}
            <div className="lg:col-span-2 bg-white border border-gray-200 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">14-Day Activity</h2>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="gApplied" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.15} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="gEmailed" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.12} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} />
                  <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Area type="monotone" dataKey="Applied" stroke="#3b82f6" fill="url(#gApplied)" strokeWidth={2} />
                  <Area type="monotone" dataKey="Emailed" stroke="#10b981" fill="url(#gEmailed)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Pipeline */}
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">Application Pipeline</h2>
              <PipelineBar pipeline={pipeline} />
              <div className="mt-4 pt-4 border-t border-gray-100 text-xs text-gray-400 flex justify-between">
                <span>Total tracked: {jobs.length}</span>
                <span>{((totalApplied / Math.max(jobs.length, 1)) * 100).toFixed(0)}% applied</span>
              </div>
            </div>

            {/* Recent high-priority jobs */}
            <div className="lg:col-span-2 bg-white border border-gray-200 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">Top Matches — Pending Action</h2>
              <div className="space-y-2">
                {jobs.filter(j => j.status === "matched").slice(0, 6).map((job) => (
                  <div key={job.id} className="flex items-center gap-3 py-2.5 border-b border-gray-50 last:border-0">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-800 truncate">{job.title}</div>
                      <div className="text-xs text-gray-400">{job.company} · {job.location || "India"}</div>
                    </div>
                    <ATSBadge score={job.ats_score} />
                    <a href={job.apply_url} target="_blank" rel="noopener noreferrer"
                       className="text-blue-500 hover:text-blue-700">
                      <ExternalLink size={14} />
                    </a>
                  </div>
                ))}
                {jobs.filter(j => j.status === "matched").length === 0 && (
                  <p className="text-sm text-gray-400 py-4 text-center">No pending matched jobs</p>
                )}
              </div>
            </div>

            {/* Today's outreach */}
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">Today's Outreach</h2>
              <div className="space-y-2">
                {outreach
                  .filter(o => new Date(o.sent_at || o.created_at).toDateString() === new Date().toDateString())
                  .slice(0, 6)
                  .map((o) => (
                    <div key={o.id} className="flex items-start gap-2 py-2 border-b border-gray-50 last:border-0">
                      <div className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${
                        o.status === "sent" ? "bg-emerald-400" :
                        o.status === "replied" ? "bg-blue-500" :
                        o.status === "failed" ? "bg-red-400" : "bg-gray-300"
                      }`} />
                      <div className="min-w-0">
                        <div className="text-xs font-medium text-gray-700">
                          {o.recruiters?.name || "HR"} @ {o.recruiters?.company}
                        </div>
                        <div className="text-xs text-gray-400 truncate">{o.subject}</div>
                      </div>
                    </div>
                  ))}
                {todayEmails === 0 && (
                  <p className="text-sm text-gray-400 py-4 text-center">No emails sent yet today</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Jobs Tab ──────────────────────────────────────────────────────── */}
        {tab === "jobs" && (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div className="p-4 border-b border-gray-100 flex items-center gap-3">
              <div className="relative flex-1 max-w-xs">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search jobs..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <span className="text-xs text-gray-400">{filteredJobs.length} jobs</span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    <th className="text-left px-4 py-3">Role</th>
                    <th className="text-left px-4 py-3">Company</th>
                    <th className="text-left px-4 py-3">Location</th>
                    <th className="text-center px-4 py-3">ATS</th>
                    <th className="text-left px-4 py-3">Status</th>
                    <th className="text-left px-4 py-3">Platform</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {filteredJobs.map((job) => (
                    <tr key={job.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 font-medium text-gray-800 max-w-xs truncate">{job.title}</td>
                      <td className="px-4 py-3 text-gray-600">{job.company}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">
                        {job.is_remote ? "🌐 Remote" : job.location || "India"}
                      </td>
                      <td className="px-4 py-3 text-center"><ATSBadge score={job.ats_score} /></td>
                      <td className="px-4 py-3"><StatusPill status={job.status} /></td>
                      <td className="px-4 py-3 text-xs text-gray-400 capitalize">{job.platform}</td>
                      <td className="px-4 py-3">
                        <a href={job.apply_url} target="_blank" rel="noopener noreferrer"
                           className="text-blue-500 hover:text-blue-700">
                          <ExternalLink size={14} />
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {filteredJobs.length === 0 && (
              <div className="py-12 text-center text-gray-400 text-sm">
                No jobs found. Run the scraper to fetch new postings.
              </div>
            )}
          </div>
        )}

        {/* ── Outreach Tab ──────────────────────────────────────────────────── */}
        {tab === "outreach" && (
          <div className="space-y-4">
            {/* Stats row */}
            <div className="grid grid-cols-4 gap-3">
              {["sent", "opened", "replied", "failed"].map((s) => {
                const count = outreach.filter(o => o.status === s).length;
                const icons = { sent: Send, opened: Eye, replied: CheckCircle2, failed: AlertCircle };
                const Icon = icons[s];
                const colors = {
                  sent: "text-blue-600", opened: "text-amber-600",
                  replied: "text-emerald-600", failed: "text-red-500"
                };
                return (
                  <div key={s} className="bg-white border border-gray-200 rounded-xl p-4">
                    <div className={`flex items-center gap-2 ${colors[s]}`}>
                      <Icon size={16} />
                      <span className="text-xs font-medium uppercase">{s}</span>
                    </div>
                    <div className="text-2xl font-semibold text-gray-800 mt-1">{count}</div>
                  </div>
                );
              })}
            </div>

            {/* Outreach table */}
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 text-xs font-medium text-gray-500 uppercase tracking-wide">
                      <th className="text-left px-4 py-3">Recruiter</th>
                      <th className="text-left px-4 py-3">Company</th>
                      <th className="text-left px-4 py-3">Subject</th>
                      <th className="text-center px-4 py-3">Status</th>
                      <th className="text-left px-4 py-3">Sent</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {outreach.map((o) => (
                      <tr key={o.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-800">
                          {o.recruiters?.name || "—"}
                        </td>
                        <td className="px-4 py-3 text-gray-600">{o.recruiters?.company || "—"}</td>
                        <td className="px-4 py-3 text-gray-500 text-xs max-w-xs truncate">{o.subject}</td>
                        <td className="px-4 py-3 text-center">
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                            o.status === "sent" ? "bg-blue-100 text-blue-700" :
                            o.status === "replied" ? "bg-emerald-100 text-emerald-700" :
                            o.status === "opened" ? "bg-amber-100 text-amber-700" :
                            o.status === "failed" ? "bg-red-100 text-red-600" :
                            "bg-gray-100 text-gray-600"
                          }`}>
                            {o.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-400">
                          {o.sent_at ? new Date(o.sent_at).toLocaleDateString("en-IN") : "Queued"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ── LinkedIn Tab ──────────────────────────────────────────────────── */}
        {tab === "linkedin" && (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
              {posts.map((post) => (
                <div key={post.id} className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                      post.status === "published" ? "bg-emerald-100 text-emerald-700" :
                      post.status === "scheduled" ? "bg-blue-100 text-blue-700" :
                      post.status === "pending_review" ? "bg-amber-100 text-amber-700" :
                      "bg-gray-100 text-gray-600"
                    }`}>
                      {post.status.replace("_", " ")}
                    </span>
                    <span className="text-xs text-gray-400 capitalize">
                      {post.post_type.replace("_", " ")}
                    </span>
                  </div>
                  <p className="text-sm text-gray-700 line-clamp-4 leading-relaxed">
                    {post.content}
                  </p>
                  <div className="pt-2 border-t border-gray-100 flex items-center justify-between">
                    <div className="flex gap-3 text-xs text-gray-400">
                      {post.status === "published" && (
                        <>
                          <span>👁 {post.impressions || 0}</span>
                          <span>❤️ {post.reactions || 0}</span>
                        </>
                      )}
                    </div>
                    <span className="text-xs text-gray-400">
                      {post.published_at
                        ? new Date(post.published_at).toLocaleDateString("en-IN")
                        : post.scheduled_for
                        ? `📅 ${new Date(post.scheduled_for).toLocaleDateString("en-IN")}`
                        : "Draft"}
                    </span>
                  </div>
                </div>
              ))}
              {posts.length === 0 && (
                <div className="col-span-3 py-16 text-center text-gray-400 text-sm">
                  No posts yet. Run the LinkedIn scheduler to generate content.
                </div>
              )}
            </div>
          </div>
        )}

      </main>
    </div>
  );
}
