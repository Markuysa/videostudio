import { useCallback, useEffect, useState } from "react";
import { Clapperboard, Sparkles, Trash2 } from "lucide-react";
import { api, type Job, type PlanDetail } from "../api";
import { Button, Chip, KV, Modal, Tabs, Textarea, useToast } from "../components/ui";
import { useStore } from "../store";

type Tab = "shots" | "issues" | "json";
export function PlanModal({ name, initialTab = "shots" }: { name: string; initialTab?: Tab }) {
  const { refresh, setModal } = useStore();
  const toast = useToast();
  const [d, setD] = useState<PlanDetail | null>(null);
  const [tab, setTab] = useState<Tab>(initialTab);
  const [raw, setRaw] = useState("");
  const load = useCallback(async () => {
    try { const x = await api<PlanDetail>(`/api/plan/${name}`); setD(x); setRaw(x.raw); } catch (e) { toast((e as Error).message, true); setModal(null); }
  }, [name, toast, setModal]);
  useEffect(() => { void load(); }, [load]);
  const close = () => setModal(null);
  const p = d?.plan;
  const errs = d?.issues.filter((i) => i.level === "error").length ?? 0;
  const warns = (d?.issues.length ?? 0) - errs;
  const render = async () => {
    if (!confirm("Start the render on RunPod? This costs money.")) return;
    try { const j = await api<Job>("/api/render", { method: "POST", body: JSON.stringify({ plan: name }) }); toast("Render started"); await refresh(); setModal({ type: "job", id: j.id }); }
    catch (e) { toast((e as Error).message, true); }
  };
  const fix = async () => {
    try { const j = await api<Job>("/api/review", { method: "POST", body: JSON.stringify({ plan: name }) }); toast("Director review and prompt fixes started"); await refresh(); setModal({ type: "job", id: j.id }); }
    catch (e) { toast((e as Error).message, true); }
  };
  const del = async () => {
    if (!confirm(`Delete plan ${name}?`)) return;
    await api(`/api/plan/${name}`, { method: "DELETE" }); close(); await refresh();
  };
  const save = async () => {
    try { const x = await api<PlanDetail>(`/api/plan/${name}`, { method: "PUT", body: raw }); setD(x); setRaw(x.raw); toast("Plan saved"); setTab("issues"); await refresh(); }
    catch (e) { toast((e as Error).message, true); }
  };
  const brief = (p?.creative_brief ?? {}) as Record<string, unknown>;
  return (
    <Modal open onClose={close} wide title={p?.title ?? name} subtitle={<span className="mono">{d?.path ?? name}</span>}
      actions={<>
        <Button size="sm" icon={<Sparkles size={14} />} title="Director review against your request, continuity checks and prompt fixes" onClick={fix}>Fix prompts</Button>
        <Button size="sm" variant="primary" icon={<Clapperboard size={14} />} onClick={render}>Render</Button>
        <Button size="sm" variant="danger" icon={<Trash2 size={14} />} onClick={del}>Delete</Button>
      </>}>
      {!d ? <div className="text-dim">Loading…</div> : (<>
        {d.summary && <pre className="text-[12.5px] text-muted whitespace-pre-wrap m-0 mb-3 font-sans">{d.summary}</pre>}
        <Tabs value={tab} onChange={setTab} tabs={[
          { value: "shots", label: "Shots" },
          { value: "issues", label: <span className="flex items-center gap-1.5">Check {errs > 0 && <Chip tone="bad">{errs}</Chip>} {warns > 0 && <Chip tone="warn">{warns}</Chip>}</span> },
          { value: "json", label: "JSON" },
        ]} />
        {tab === "json" && (<>
          <Textarea value={raw} onChange={(e) => setRaw(e.target.value)} className="mono min-h-[460px] whitespace-pre" spellCheck={false} />
          <div className="flex items-center gap-3 mt-3"><Button variant="primary" onClick={save}>Save</Button><span className="text-muted text-[13px]">After saving, the plan is re-checked by the linter</span></div>
        </>)}
        {tab === "issues" && (d.problems.length || d.issues.length ? (
          <div className="grid gap-1 text-[13.5px]">
            {d.problems.map((x, i) => <div key={i} className="text-bad">⛔ {x}</div>)}
            {d.issues.map((i, k) => <div key={k} className={i.level === "error" ? "text-bad" : "text-warn"}>{i.level === "error" ? "✖" : "▲"} shot {i.shot} · {i.code}: {i.message}</div>)}
          </div>
        ) : <div className="text-dim text-center py-6">No issues</div>)}
        {tab === "shots" && (p ? (<>
          <div className="mb-4"><KV rows={[
            ["Logline", p.logline || "—"], ["Synopsis", p.synopsis || "—"],
            ["Style", <span className="text-[13px]">{Object.entries(p.style || {}).map(([k, v]) => <span key={k} className="mr-2"><b>{k}</b>: {v}</span>)}</span>],
            ...(Object.keys(brief).length ? [["Creative brief", <span className="text-[13px]">{Object.entries(brief).map(([k, v]) => <div key={k}><b>{k}</b>: {Array.isArray(v) ? v.join("; ") : String(v ?? "—")}</div>)}</span>] as [string, React.ReactNode]] : []),
            ...(p.review_notes?.length ? [["Director review", <div className="text-[13px] grid gap-1">{p.review_notes.map((n, i) => <div key={i}>• {n}</div>)}</div>] as [string, React.ReactNode]] : []),
            ["Characters", <span className="text-[13px]">{p.characters.length ? p.characters.map((c) => <div key={c.name}><b>{c.name}</b> — {c.descriptor || c.description}</div>) : "—"}</span>],
            ["Music", p.music ? `${p.music.file || "(no track chosen)"}${p.music.mood ? ` · ${p.music.mood}` : ""}` : "—"],
          ]} /></div>
          <div className="grid gap-2.5">
            {p.shots.map((s, i) => (
              <div key={s.id} className="border border-line rounded-lg p-3.5 bg-bg-2 grid gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="mono font-bold text-accent">{s.id}</span><Chip>{s.seconds} s</Chip>
                  {i > 0 && <Chip tone={s.transition === "continue" ? "info" : s.transition === "dissolve" ? "accent" : "default"}>{s.transition || "cut"}</Chip>}
                  {s.caption && <Chip tone="warn">💬 {s.caption}</Chip>}
                  {(s.sfx ?? []).map((x) => <Chip key={x.file}>🔊 {x.file.split("/").pop()}</Chip>)}
                  {s.beat && <span className="text-muted text-[12.5px]">{s.beat}</span>}
                </div>
                <p className="m-0 text-[14px] text-[#cdd3df] leading-relaxed">{s.prompt}</p>
                {s.direction && Object.keys(s.direction).length > 0 && (
                  <details><summary className="text-[12.5px] text-muted hover:text-text">Shot direction ▾</summary>
                    <div className="text-[13px] mt-1.5 grid gap-0.5">{Object.entries(s.direction).map(([k, v]) => <div key={k}><b className="text-muted">{k}</b>: {v}</div>)}</div></details>
                )}
              </div>
            ))}
          </div>
        </>) : <div className="text-bad">{d.error}</div>)}
      </>)}
    </Modal>
  );
}
