export interface PlanRow {
  name: string; title: string; kind?: string; format?: string; quality?: string; shots?: number; seconds?: number;
  logline?: string | null; series?: string | null; episode?: number | null; modified: number; has_film?: boolean; film_slug?: string | null;
  captions?: boolean; music?: boolean; loop?: boolean; audio?: string; anchor?: string | null;
  errors?: number; warnings?: number; review_notes?: number; broken?: boolean;
}
export interface ShotInfo { id: string; pipeline: string; size?: string; seconds_render?: number; continuity?: boolean; loop_closed?: boolean; cached?: boolean }
export interface TimelineItem { shot: string; start: number; end: number; transition: string; caption?: string | null }
export interface Film {
  slug: string; title: string; file: string; seconds?: number | null; resolution?: string | null; quality?: string | null;
  shots_ok?: number | null; shots_failed: string[]; shots: ShotInfo[]; timeline: TimelineItem[]; music?: boolean; captions?: boolean;
  minutes?: number | null; modified: number; size: number; has_clips: boolean; has_manifest: boolean; recuts: string[]; legacy?: boolean;
}
export interface SeriesRow { slug: string; title: string; premise?: string; episodes: number; characters: number; planned: number }
export interface Job {
  id: string; kind: string; title: string; status: "queued" | "running" | "done" | "error" | "stopped";
  started: number | null; finished: number | null; returncode: number | null; pid: number | null; meta: Record<string, unknown>;
  stage: string; shot: number | null; shots: number | null; result: string | null; error?: string; log?: string;
}
export interface LibraryEntry { file: string; tags: string[]; mood?: string; seconds?: number | null }
export interface Config {
  quality: string; llm_provider: string; llm_effective: string; llm_model: string; has_anthropic: boolean; has_runpod: boolean;
  has_elevenlabs: boolean; gpu_price: number; gpu_types?: string[]; max_hours?: number; ffmpeg: boolean; config_path: string;
  kinds: string[]; formats: string[];
}
export interface State {
  plans: PlanRow[]; films: Film[]; series: SeriesRow[]; jobs: Job[]; library: { music: LibraryEntry[]; sfx: LibraryEntry[] };
  config: Config; prefs: string; now: number;
}
export interface Shot {
  id: string; seconds: number; prompt: string; transition?: string; transition_seconds?: number; caption?: string | null;
  narration?: string | null; sfx?: { file: string; offset: number; volume: number }[]; beat?: string | null; direction?: Record<string, string>;
}
export interface Plan {
  title: string; kind: string; format: string; quality?: string | null; seed: number; logline?: string | null; synopsis?: string | null;
  style: Record<string, string>; characters: { name: string; descriptor?: string; description?: string; voice?: string }[];
  locations?: { name: string; descriptor?: string }[]; music?: { file?: string | null; mood?: string | null; volume: number; duck: boolean } | null;
  captions: { enabled: boolean }; loop?: boolean; audio?: "raw" | "leveled"; creative_brief?: Record<string, unknown>; review_notes?: string[]; shots: Shot[];
}
export interface Issue { shot: string; level: "error" | "warn"; code: string; message: string }
export interface PlanDetail { name: string; plan?: Plan; raw: string; summary?: string; issues: Issue[]; problems: string[]; path?: string; error?: string }
export interface Bible {
  title: string; premise?: string; tone?: string; genre?: string; style?: Record<string, string>; sound_signature?: string;
  characters?: { name: string; descriptor: string; description?: string; voice?: string; arc?: string }[];
  locations?: { name: string; descriptor: string }[]; season_arc?: string[];
  episodes?: { episode: number; slug: string; title: string; logline?: string; summary?: string }[]; notes?: string[];
}

export class ApiError extends Error {}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string> | undefined) } });
  let data: unknown = null;
  try { data = await r.json(); } catch { /* пустой ответ */ }
  if (!r.ok) throw new ApiError((data as { error?: string } | null)?.error || `HTTP ${r.status}`);
  return data as T;
}

export const fmtDur = (s?: number | null) => {
  if (s == null) return "—";
  const r = Math.round(s);
  return r >= 60 ? `${Math.floor(r / 60)} min ${r % 60} s` : `${r} s`;
};
export const fmtAgo = (t?: number | null) => {
  if (!t) return "";
  const d = Date.now() / 1000 - t;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString("en-GB");
};
export const fmtSize = (b: number) => (b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`);
export const elapsed = (j: Job) => {
  if (!j.started) return "";
  const s = Math.round((j.finished || Date.now() / 1000) - j.started);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
};

export const KINDS: Record<string, { label: string; desc: string; durations: number[]; def: number; lo: number; hi: number }> = {
  short: { label: "Short", desc: "9:16, hook, captions, 15–60 s", durations: [15, 30, 45, 60], def: 45, lo: 3, hi: 8 },
  aesthetic: { label: "Aesthetic", desc: "mood piece under music, long takes", durations: [30, 45, 60, 90], def: 45, lo: 5, hi: 10 },
  film: { label: "Film", desc: "drama, 2–10 min", durations: [120, 180, 300, 480], def: 180, lo: 4, hi: 10 },
  episode: { label: "Episode", desc: "episode from a series bible", durations: [90, 120, 180, 300], def: 120, lo: 4, hi: 10 },
  motion: { label: "Motion", desc: "graphic animation, 6–90 s", durations: [6, 15, 30, 60], def: 15, lo: 3, hi: 8 },
};
export const LANGS = [["ru", "Russian"], ["en", "English"], ["es", "Español"], ["fr", "Français"], ["de", "Deutsch"], ["ja", "日本語"], ["it", "Italiano"]] as const;
