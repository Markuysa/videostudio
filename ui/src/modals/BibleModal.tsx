import { useCallback, useEffect, useState } from "react";
import { FileText } from "lucide-react";
import { api, type Bible } from "../api";
import { Button, Chip, Input, KV, Modal, useToast } from "../components/ui";
import { useStore } from "../store";

export function BibleModal({ slug }: { slug: string }) {
  const { setModal, setView } = useStore();
  const toast = useToast();
  const [b, setB] = useState<Bible | null>(null);
  const [note, setNote] = useState("");
  const load = useCallback(async () => { try { setB(await api<Bible>(`/api/series/${slug}`)); } catch (e) { toast((e as Error).message, true); setModal(null); } }, [slug, toast, setModal]);
  useEffect(() => { void load(); }, [load]);
  const add = async () => { if (!note.trim()) return; await api("/api/series/note", { method: "POST", body: JSON.stringify({ name: slug, text: note }) }); setNote(""); toast("Note added"); await load(); };
  return (
    <Modal open onClose={() => setModal(null)} wide title={b?.title ?? slug} subtitle={<span className="mono">{slug}</span>}
      actions={<Button size="sm" variant="primary" icon={<FileText size={14} />} onClick={() => { setModal(null); setView("studio"); toast(`Choose “${b?.title ?? slug}” in More settings → Series and describe the episode`); }}>New episode</Button>}>
      {!b ? <div className="text-dim">Loading…</div> : (<>
        <KV rows={[["Premise", b.premise ?? "—"], ["Tone", `${b.tone ?? ""} · ${b.genre ?? ""}`],
          ["Style", <span className="text-[13px]">{Object.entries(b.style ?? {}).map(([k, v]) => <span key={k} className="mr-2"><b>{k}</b>: {v}</span>)}</span>],
          ["Sound", <span className="text-[13px]">{b.sound_signature}</span>]]} />
        <h4 className="mt-5 mb-2 text-[14px] font-bold">Characters</h4>
        <div className="grid gap-2">{(b.characters ?? []).map((c) => (
          <div key={c.name} className="border border-line rounded-lg p-3 bg-bg-2"><div className="flex flex-wrap items-center gap-2"><b>{c.name}</b><Chip tone="accent">{c.descriptor}</Chip></div>
            <p className="m-0 mt-1.5 text-[13.5px] text-[#cdd3df]">{c.description} <span className="text-muted">Voice: {c.voice}. Arc: {c.arc}</span></p></div>
        ))}</div>
        <h4 className="mt-5 mb-2 text-[14px] font-bold">Season arc</h4>
        <ol className="m-0 pl-5 text-[13.5px] grid gap-1">{(b.season_arc ?? []).map((a, i) => <li key={i}>{a}</li>)}</ol>
        <h4 className="mt-5 mb-2 text-[14px] font-bold">Episodes made</h4>
        {(b.episodes ?? []).length ? (b.episodes ?? []).map((e) => <div key={e.episode} className="text-[13.5px]">Ep. {e.episode}: <b>{e.title}</b> — {e.summary || e.logline} <span className="text-dim">({e.slug}.json)</span></div>) : <div className="text-dim text-[13px]">none yet</div>}
        <h4 className="mt-5 mb-2 text-[14px] font-bold">Continuity notes</h4>
        {(b.notes ?? []).map((n, i) => <div key={i} className="text-[13.5px]">• {n}</div>)}
        <div className="flex gap-2 mt-2.5"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. the hero now has a scar on his left cheek" /><Button size="sm" onClick={add}>Add</Button></div>
      </>)}
    </Modal>
  );
}
