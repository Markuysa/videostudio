import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Clapperboard, FileText } from "lucide-react";
import { api, KINDS, LANGS, type Job } from "../api";
import { Button, Empty, Field, Input, Segmented, Select, Stat, Textarea, Toggle, useToast } from "../components/ui";
import { JobCard } from "../components/JobCard";
import { FilmCard } from "../components/FilmCard";
import { PromptAssistant } from "../components/PromptAssistant";
import { PageHeader } from "../components/PageHeader";
import { useStore } from "../store";

interface Form {
  request: string; kind: string; duration: number; custom: boolean; format: string; quality: string; language: string;
  music: string; captions: "" | "1" | "0"; series: string; name: string; notes: string; loop: boolean; audio: "raw" | "leveled";
}
const initial: Form = { request: "", kind: "short", duration: 45, custom: false, format: "", quality: "", language: "ru", music: "auto", captions: "", series: "", name: "", notes: "", loop: false, audio: "raw" };

export function Studio() {
  const { state, refresh, setModal, setView, prefill, setPrefill } = useStore();
  const toast = useToast();
  const [f, setF] = useState<Form>(initial);
  const [adv, setAdv] = useState(false);
  const [direction, setDirection] = useState<{ text: string; source: string } | null>(null);
  const assistantContext = { request: f.request, kind: f.series ? "episode" : f.kind, series: f.series, duration: f.duration,
    format: f.format, language: f.language, music: f.music, captions: f.captions, loop: f.loop, notes: f.notes };
  const directionCurrent = direction?.source === JSON.stringify(assistantContext);
  useEffect(() => {
    if (!prefill) return;
    setF((p) => ({ ...p, ...(prefill.kind ? { kind: prefill.kind, duration: KINDS[prefill.kind]?.def ?? p.duration, custom: false } : {}),
      ...(prefill.series ? { series: prefill.series } : {}), ...(prefill.request ? { request: prefill.request } : {}) }));
    if (prefill.series) setAdv(true);
    setPrefill(null);
  }, [prefill, setPrefill]);
  const [busy, setBusy] = useState(false);
  const s = state!;
  const kind = KINDS[f.kind] ?? KINDS.film;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((p) => ({ ...p, [k]: v }));

  const estimate = useMemo(() => {
    const secs = f.duration || kind.def;
    const shots = Math.max(1, Math.round(secs / ((kind.lo + kind.hi) / 2)));
    const high = (f.quality || s.config.quality) === "high";
    const minutes = shots * (high ? 3.2 : 1.3) + 6;
    return `≈ ${shots} shots · ~${Math.round(minutes)} min render`;
  }, [f.duration, f.quality, kind, s.config]);

  const submit = async (render: boolean) => {
    if (!f.request.trim()) { toast("Describe what we are shooting", true); return; }
    if (render && !s.config.has_runpod) { toast("RunPod is not configured — fill in film_config.json", true); return; }
    setBusy(true);
    try {
      const notes = [f.notes, directionCurrent ? direction?.text : ""].filter(Boolean).join("\n\n");
      const body = { ...f, notes, render, duration: f.duration || null, captions: f.captions === "" ? null : f.captions === "1", kind: f.series ? "episode" : f.kind };
      const job = await api<Job>("/api/plan", { method: "POST", body: JSON.stringify(body) });
      toast(render ? "Started: script, then render" : "Writing the script");
      setF((p) => ({ ...p, request: "", notes: "", name: "" }));
      setDirection(null);
      await refresh();
      setModal({ type: "job", id: job.id });
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };

  const kindOpts = s.config.kinds.filter((k) => KINDS[k]).map((k) => ({ value: k, label: KINDS[k].label }));
  const recentJobs = s.jobs.filter((j) => j.status === "running" || Date.now() / 1000 - (j.finished || 0) < 3600).slice(0, 5);
  const musicOpts = [{ value: "auto", label: "From the library" }, { value: "none", label: "No music" }, ...s.library.music.map((m) => ({ value: m.file, label: m.file.split("/").pop()! }))];

  return (
    <>
      <PageHeader title="What are we shooting?" subtitle="Describe the idea in your own words. The studio does the rest: script, prompts, rendering, editing." />
      <div className="grid grid-cols-[1.45fr_1fr] gap-5 max-lg:grid-cols-1">
        <div className="card p-6 grid gap-4">
          <Textarea value={f.request} onChange={(e) => set("request", e.target.value)} rows={4} className="text-[16.5px] min-h-[130px] p-4"
            placeholder="For example: an aesthetic short about a rainy evening in Tokyo — a girl with a red umbrella walks down a neon street, lo-fi mood" />
          <PromptAssistant context={assistantContext} onApply={(text) => setDirection({ text, source: JSON.stringify(assistantContext) })} />
          {direction && <div className="text-sm text-muted">
            {directionCurrent ? "Creative direction is applied to the next script." : "Settings changed: apply updated direction before using it."}
            <Button variant="link" onClick={() => setDirection(null)}>Remove direction</Button>
          </div>}
          <Segmented full value={f.kind} options={kindOpts} onChange={(k) => setF((p) => ({ ...p, kind: k, duration: KINDS[k].def, custom: false }))} />
          <div className="text-[12.5px] text-muted -mt-2">{kind.desc}</div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="label">Duration</span>
            <Segmented size="sm" value={f.custom ? "custom" : String(f.duration)} onChange={(v) => v === "custom" ? set("custom", true) : setF((p) => ({ ...p, custom: false, duration: Number(v) }))}
              options={[...kind.durations.map((d) => ({ value: String(d), label: d < 120 ? `${d} s` : `${Math.round(d / 60)} min` })), { value: "custom", label: "custom" }]} />
            {f.custom && <Input type="number" min={6} max={900} value={f.duration} onChange={(e) => set("duration", Number(e.target.value))} className="w-24 text-center py-2" />}
            <span className="text-[12.5px] text-muted ml-auto">{estimate}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2.5 pt-3 border-t border-line">
            <Button variant="primary" size="lg" icon={<Clapperboard size={18} />} disabled={busy} onClick={() => submit(true)}>Shoot</Button>
            <Button variant="ghost" icon={<FileText size={16} />} disabled={busy} onClick={() => submit(false)}>Script only</Button>
            <Button variant="link" className="ml-auto" icon={adv ? <ChevronUp size={15} /> : <ChevronDown size={15} />} onClick={() => setAdv((a) => !a)}>{adv ? "Hide settings" : "More settings"}</Button>
          </div>
          {adv && (
            <div className="rise grid gap-3.5 pt-3.5 border-t border-dashed border-line">
              <div className="grid grid-cols-3 gap-3 max-sm:grid-cols-1">
                <Field label="Format"><Select value={f.format} onChange={(v) => set("format", v)} options={[{ value: "", label: "By preset" }, ...s.config.formats.map((x) => ({ value: x, label: x }))]} /></Field>
                <Field label="Quality"><Select value={f.quality} onChange={(v) => set("quality", v)} options={[{ value: "", label: `Default (${s.config.quality})` }, { value: "high", label: "High", hint: "DFR 1080p, 96 GB GPU" }, { value: "fast", label: "Fast", hint: "720p, faster and cheaper" }]} /></Field>
                <Field label="Dialogue language"><Select value={f.language} onChange={(v) => set("language", v)} options={LANGS.map(([v, l]) => ({ value: v, label: l }))} /></Field>
                <Field label="Music"><Select value={f.music} onChange={(v) => set("music", v)} options={musicOpts} /></Field>
                <Field label="Captions"><Select value={f.captions} onChange={(v) => set("captions", v)} options={[{ value: "", label: "By preset" }, { value: "1", label: "On" }, { value: "0", label: "Off" }]} /></Field>
                <Field label="Series"><Select value={f.series} onChange={(v) => set("series", v)} options={[{ value: "", label: "—" }, ...s.series.map((x) => ({ value: x.slug, label: x.title }))]} /></Field>
                <Field label="Audio"><Select value={f.audio} onChange={(v) => set("audio", v)} options={[{ value: "raw", label: "As generated", hint: "the model's sound untouched" }, { value: "leveled", label: "Leveled", hint: "scenes matched, -14 LUFS, limiter" }]} /></Field>
              </div>
              <div className="grid grid-cols-[1fr_2fr] gap-3 max-sm:grid-cols-1">
                <Field label="File name"><Input value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="auto" /></Field>
                <Field label="Creative direction · what must stay exact"><Input value={f.notes} onChange={(e) => set("notes", e.target.value)} placeholder="e.g. natural overcast light, locked camera, no neon or dialogue, photoreal" /></Field>
              </div>
              <Toggle checked={f.loop} onChange={(v) => set("loop", v)} label="Seamless loop: the end flows into the beginning" />
            </div>
          )}
        </div>
        <div className="grid gap-5 content-start">
          <div className="card p-5">
            <div className="flex items-center justify-between mb-3"><h3 className="m-0 text-[15px] font-bold">Jobs</h3><button className="text-[13px] text-info hover:underline cursor-pointer" onClick={() => setView("jobs")}>all →</button></div>
            {recentJobs.length ? <div className="grid gap-2.5">{recentJobs.map((j) => <JobCard key={j.id} job={j} />)}</div> : <Empty>Nothing is running right now</Empty>}
          </div>
          <div className="card p-5 flex justify-around">
            <Stat value={s.plans.length} label="plans" /><Stat value={s.films.length} label="films" /><Stat value={s.series.length} label="series" /><Stat value={s.library.music.length + s.library.sfx.length} label="sounds" />
          </div>
        </div>
      </div>
      {s.films.length > 0 && (<>
        <h2 className="text-[17px] font-bold mt-8 mb-3">Recent films</h2>
        <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(420px,1fr))] max-sm:grid-cols-1">{s.films.slice(0, 2).map((f) => <FilmCard key={f.slug} film={f} />)}</div>
      </>)}
    </>
  );
}
