import { useEffect, useMemo, useState } from "react";
import { Calculator, Clapperboard, FileText, Film, ListX, Music2, ScrollText, Sparkles, Square, Trash2, Tv, type LucideIcon } from "lucide-react";
import { api, elapsed, fmtAgo, type Job } from "../api";
import { Button, Chip, Empty, Progress, Segmented, Stat, useToast } from "../components/ui";
import { jobPct, STATUS } from "../components/JobCard";
import { useStore } from "../store";

const KIND: Record<string, { label: string; icon: LucideIcon }> = {
  plan: { label: "Script", icon: FileText }, make: { label: "Script + render", icon: Clapperboard }, render: { label: "Render", icon: Film },
  review: { label: "Prompt fixes", icon: Sparkles }, assemble: { label: "Re-assembly", icon: Music2 }, series: { label: "Series bible", icon: Tv },
  estimate: { label: "Estimate", icon: Calculator },
};
type Filter = "all" | "running" | "done" | "error";

function dayGroup(j: Job, now: number): string {
  if (j.status === "running" || j.status === "queued") return "Now";
  const t = j.finished || j.started || 0;
  const d = new Date(t * 1000), n = new Date(now * 1000);
  if (d.toDateString() === n.toDateString()) return "Today";
  const y = new Date(n); y.setDate(n.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return "Earlier";
}

export function Jobs() {
  const { state, refresh, setModal, setView } = useStore();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [, tick] = useState(0);
  useEffect(() => { const t = window.setInterval(() => tick((x) => x + 1), 1000); return () => window.clearInterval(t); }, []);
  const jobs = state!.jobs;
  const counts = useMemo(() => ({
    running: jobs.filter((j) => j.status === "running" || j.status === "queued").length,
    done: jobs.filter((j) => j.status === "done").length,
    error: jobs.filter((j) => j.status === "error" || j.status === "stopped").length,
  }), [jobs]);
  const shown = jobs.filter((j) => filter === "all" ? true : filter === "running" ? (j.status === "running" || j.status === "queued") : filter === "done" ? j.status === "done" : (j.status === "error" || j.status === "stopped"));
  const groups: [string, Job[]][] = [];
  for (const j of shown) {
    const g = dayGroup(j, state!.now);
    const last = groups[groups.length - 1];
    if (last && last[0] === g) last[1].push(j); else groups.push([g, [j]]);
  }
  const stop = async (j: Job) => {
    if (!confirm("Stop the job? The render will still download the log and delete the Pod.")) return;
    await api(`/api/jobs/${j.id}/stop`, { method: "POST" }); await refresh();
  };
  const del = async (j: Job) => { await api(`/api/jobs/${j.id}`, { method: "DELETE" }); await refresh(); };
  const clear = async () => {
    if (!confirm("Remove all finished jobs from the list? Logs are deleted too.")) return;
    const r = await api<{ removed: number }>("/api/jobs", { method: "DELETE" }); toast(`Removed ${r.removed} jobs`); await refresh();
  };
  const planName = (j: Job) => j.result && /\.json$/.test(j.result) ? j.result.split("/").pop()!.replace(/\.json$/, "") : (j.meta.plan as string | undefined);

  return (
    <>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[28px] font-extrabold tracking-tight m-0">Jobs</h1>
          <p className="text-muted mt-1 mb-5">Scripts, renders and re-assemblies run as separate processes. Closing this page or the server does not stop them.</p>
        </div>
        <Button variant="ghost" size="sm" icon={<ListX size={14} />} onClick={clear} disabled={counts.done + counts.error === 0}>Clear finished</Button>
      </div>
      <div className="card p-5 mb-5 flex flex-wrap items-center gap-8">
        <Stat value={<span className={counts.running ? "text-accent" : ""}>{counts.running}</span>} label="running" />
        <Stat value={counts.done} label="done" />
        <Stat value={<span className={counts.error ? "text-bad" : ""}>{counts.error}</span>} label="failed / stopped" />
        <div className="ml-auto">
          <Segmented size="sm" value={filter} onChange={setFilter} options={[{ value: "all", label: `All ${jobs.length}` }, { value: "running", label: "Running" }, { value: "done", label: "Done" }, { value: "error", label: "Failed" }]} />
        </div>
      </div>
      {shown.length === 0 ? <Empty>{jobs.length ? "Nothing matches this filter" : "No jobs yet. Start one on the Studio tab."}</Empty> : groups.map(([name, list]) => (
        <section key={name} className="mb-6">
          <h2 className="text-[12px] font-semibold uppercase tracking-wider text-muted mb-2.5">{name}</h2>
          <div className="card overflow-hidden divide-y divide-line">
            {list.map((j) => {
              const k = KIND[j.kind] ?? { label: j.kind, icon: ScrollText };
              const Icon = k.icon; const st = STATUS[j.status]; const pct = jobPct(j); const live = j.status === "running";
              const pn = planName(j);
              return (
                <div key={j.id} className="grid grid-cols-[40px_1fr_auto] gap-4 px-4 py-3.5 items-center hover:bg-white/[0.015] transition max-md:grid-cols-[40px_1fr]">
                  <div className={`w-10 h-10 rounded-lg grid place-items-center ${live ? "bg-accent/15 text-accent" : j.status === "done" ? "bg-good/10 text-good" : j.status === "error" ? "bg-bad/10 text-bad" : "bg-panel-2 text-muted"}`}><Icon size={18} /></div>
                  <div className="min-w-0 grid gap-1.5 cursor-pointer" onClick={() => setModal({ type: "job", id: j.id })}>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold truncate max-w-[60ch]">{j.title}</span>
                      <Chip>{k.label}</Chip>
                      <Chip tone={st.tone}>{live && <span className="pulse w-1.5 h-1.5 rounded-full bg-accent" />}{st.label}</Chip>
                    </div>
                    {live && <div className="max-w-[520px]"><Progress value={pct} /></div>}
                    <div className="flex items-center gap-2 text-[12.5px] text-muted flex-wrap">
                      <span>{j.stage || (live ? "starting…" : "")}{j.shots ? ` · shot ${j.shot}/${j.shots}` : ""}</span>
                      {j.status === "error" && j.error && <span className="text-bad truncate max-w-[60ch]">· {j.error}</span>}
                      <span className="ml-auto whitespace-nowrap">{j.started ? `${fmtAgo(j.started)} · ${elapsed(j)}` : ""}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 justify-end max-md:col-span-2">
                    {pn && <Button size="sm" variant="ghost" onClick={() => setModal({ type: "plan", name: pn })}>Plan</Button>}
                    {j.result && /\.mp4$/.test(j.result) && <Button size="sm" variant="ghost" onClick={() => setView("films")}>Film</Button>}
                    <Button size="sm" variant="ghost" icon={<ScrollText size={13} />} onClick={() => setModal({ type: "job", id: j.id })}>Log</Button>
                    {live ? <Button size="sm" variant="danger" icon={<Square size={12} />} onClick={() => stop(j)}>Stop</Button>
                          : <Button size="sm" variant="link" icon={<Trash2 size={14} />} onClick={() => del(j)} title="Remove from list" />}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </>
  );
}
