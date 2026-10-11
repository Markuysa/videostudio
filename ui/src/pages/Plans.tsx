import { Clapperboard } from "lucide-react";
import { api, fmtAgo, fmtDur, KINDS, type Job } from "../api";
import { Button, Chip, Empty, useToast } from "../components/ui";
import { useStore } from "../store";

export function Plans() {
  const { state, refresh, setModal } = useStore();
  const toast = useToast();
  const plans = state!.plans;
  const render = async (name: string) => {
    if (!confirm("Start the render on RunPod? This costs money.")) return;
    try { const j = await api<Job>("/api/render", { method: "POST", body: JSON.stringify({ plan: name }) }); toast("Render started"); await refresh(); setModal({ type: "job", id: j.id }); }
    catch (e) { toast((e as Error).message, true); }
  };
  return (
    <>
      <h1 className="text-[28px] font-extrabold tracking-tight m-0">Plans</h1>
      <p className="text-muted mt-1 mb-6">A plan is JSON with the story, style and shot prompts. You can edit it by hand before rendering.</p>
      {plans.length === 0 ? <Empty>No plans yet. Create the first one on the Studio tab.</Empty> : (
        <div className="card overflow-hidden">
          <table className="table w-full border-collapse text-[14px]">
            <thead><tr><th>Title</th><th>Type</th><th>Shots</th><th>Running time</th><th>Quality</th><th>Modified</th><th></th></tr></thead>
            <tbody>
              {plans.map((p) => p.broken ? (
                <tr key={p.name}><td>{p.name}</td><td colSpan={5} className="text-bad">file unreadable</td><td /></tr>
              ) : (
                <tr key={p.name} className="clickable" onClick={() => setModal({ type: "plan", name: p.name })}>
                  <td><b>{p.title}</b><div className="text-[12.5px] text-muted">{p.name}.json{p.logline ? ` · ${p.logline}` : ""}</div></td>
                  <td><div className="flex gap-1.5"><Chip>{KINDS[p.kind ?? ""]?.label ?? p.kind}</Chip><Chip>{p.format}</Chip></div></td>
                  <td>{p.shots}</td><td>{fmtDur(p.seconds)}</td><td>{p.quality}</td>
                  <td className="text-muted text-[13px]">{fmtAgo(p.modified)}</td>
                  <td><div className="flex items-center justify-end gap-2">{p.has_film && <Chip tone="good">has film</Chip>}<Button size="sm" variant="primary" icon={<Clapperboard size={14} />} onClick={(e) => { e.stopPropagation(); void render(p.name); }}>Render</Button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
