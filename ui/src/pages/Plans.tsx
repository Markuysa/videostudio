import { useMemo, useState } from "react";
import { Clapperboard, FileText, Film, Play, Repeat, Search, Sparkles, Trash2, Tv, Volume2, type LucideIcon } from "lucide-react";
import { api, fmtAgo, fmtDur, KINDS, type Job, type PlanRow } from "../api";
import { Button, Chip, Empty, Input, Segmented, useToast } from "../components/ui";
import { PageHeader } from "../components/PageHeader";
import { useStore } from "../store";

const KIND_ICON: Record<string, LucideIcon> = { short: FileText, aesthetic: FileText, film: Clapperboard, episode: Tv, motion: FileText };

export function Plans() {
  const { state, refresh, setModal, setView } = useStore();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("all");
  const s = state!;
  const plans = useMemo(() => s.plans.filter((p) => (kind === "all" || p.kind === kind) &&
    (!q.trim() || `${p.title} ${p.name} ${p.logline ?? ""}`.toLowerCase().includes(q.toLowerCase()))), [s.plans, kind, q]);
  const kinds = ["all", ...Array.from(new Set(s.plans.map((p) => p.kind).filter(Boolean) as string[]))];

  const render = async (p: PlanRow) => {
    if (!confirm(`Render “${p.title}” on RunPod? This costs money.`)) return;
    try { const j = await api<Job>("/api/render", { method: "POST", body: JSON.stringify({ plan: p.name }) }); toast("Render started"); await refresh(); setModal({ type: "job", id: j.id }); }
    catch (e) { toast((e as Error).message, true); }
  };
  const fix = async (p: PlanRow) => {
    try { const j = await api<Job>("/api/review", { method: "POST", body: JSON.stringify({ plan: p.name }) }); toast("Director review and prompt fixes started"); await refresh(); setModal({ type: "job", id: j.id }); }
    catch (e) { toast((e as Error).message, true); }
  };
  const del = async (p: PlanRow) => {
    if (!confirm(`Delete plan ${p.name}?`)) return;
    await api(`/api/plan/${p.name}`, { method: "DELETE" }); toast("Plan deleted"); await refresh();
  };
  const cost = (p: PlanRow) => {
    const minutes = (p.shots ?? 0) * (p.quality === "high" ? 3.2 : 1.3) + 6;
    return `~${Math.round(minutes)} min render`;
  };

  return (
    <>
      <PageHeader title="Plans" subtitle="A plan is the script, the style bible and the shot prompts. Check it, fix it, then render."
        actions={<Button variant="primary" size="sm" icon={<FileText size={14} />} onClick={() => setView("studio")}>New script</Button>} />
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div className="relative w-[320px] max-w-full">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-dim" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by title or logline" className="pl-9" />
        </div>
        <Segmented size="sm" value={kind} onChange={setKind} options={kinds.map((k) => ({ value: k, label: k === "all" ? `All ${s.plans.length}` : KINDS[k]?.label ?? k }))} />
      </div>
      {plans.length === 0 ? <Empty>{s.plans.length ? "Nothing matches" : "No plans yet. Write the first script on the Studio tab."}</Empty> : (
        <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
          {plans.map((p) => {
            if (p.broken) return <div key={p.name} className="card p-5 text-bad">{p.name}.json — file unreadable</div>;
            const Icon = KIND_ICON[p.kind ?? ""] ?? FileText;
            const clean = !p.errors && !p.warnings;
            return (
              <div key={p.name} className="card p-5 grid gap-3 content-start hover:border-line-2 transition">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-lg bg-panel-2 text-accent grid place-items-center shrink-0"><Icon size={18} /></div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <button className="font-bold text-[16px] leading-tight text-left hover:text-accent cursor-pointer" onClick={() => setModal({ type: "plan", name: p.name })}>{p.title}</button>
                      {p.episode ? <Chip tone="info">ep. {p.episode}</Chip> : null}
                    </div>
                    <div className="mono text-dim text-[12px] mt-0.5">{p.name}.json · {fmtAgo(p.modified)}</div>
                  </div>
                  {p.has_film && p.film_slug && (
                    <button title="Play the rendered film" onClick={() => setView("films")} className="shrink-0 inline-flex items-center gap-1.5 text-[12.5px] text-good border border-good/40 rounded-full px-2.5 py-0.5 hover:bg-good/10 cursor-pointer"><Play size={11} fill="currentColor" />film ready</button>
                  )}
                </div>
                {p.logline && <p className="m-0 text-[14px] text-[#cdd3df] leading-relaxed line-clamp-2">{p.logline}</p>}
                <div className="flex flex-wrap gap-1.5">
                  <Chip>{KINDS[p.kind ?? ""]?.label ?? p.kind}</Chip><Chip>{p.format}</Chip><Chip>{p.quality}</Chip>
                  <Chip>{p.shots} shots · {fmtDur(p.seconds)}</Chip>
                  {p.loop && <Chip tone="info"><Repeat size={11} />loop</Chip>}
                  {p.captions && <Chip>💬 captions</Chip>}
                  {p.music && <Chip>♫ music</Chip>}
                  {p.audio === "leveled" && <Chip><Volume2 size={11} />leveled</Chip>}
                </div>
                <div className="flex items-center gap-2 flex-wrap text-[12.5px]">
                  {clean ? <Chip tone="good">✓ prompts clean</Chip> : (<>
                    {p.errors ? <Chip tone="bad">✖ {p.errors} errors</Chip> : null}
                    {p.warnings ? <Chip tone="warn">▲ {p.warnings} warnings</Chip> : null}
                  </>)}
                  {p.review_notes ? <Chip title="director review notes">{p.review_notes} review notes</Chip> : null}
                  <span className="text-muted ml-auto">{cost(p)}</span>
                </div>
                <div className="flex items-center gap-2 pt-2 border-t border-line">
                  <Button size="sm" onClick={() => setModal({ type: "plan", name: p.name })}>Open</Button>
                  <Button size="sm" variant="ghost" icon={<Sparkles size={13} />} onClick={() => fix(p)} title="Director review and prompt fixes">Fix</Button>
                  <Button size="sm" variant="primary" icon={<Clapperboard size={13} />} onClick={() => render(p)}>Render</Button>
                  {p.has_film && <Button size="sm" variant="ghost" icon={<Film size={13} />} onClick={() => setView("films")}>Film</Button>}
                  <Button size="sm" variant="link" className="ml-auto" icon={<Trash2 size={14} />} onClick={() => del(p)} title="Delete plan" />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
