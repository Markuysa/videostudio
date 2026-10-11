import { useEffect, useRef, useState } from "react";
import { Square, Trash2 } from "lucide-react";
import { api, elapsed, type Job } from "../api";
import { Button, Chip, Modal, Progress, useToast } from "../components/ui";
import { jobPct, STATUS } from "../components/JobCard";
import { useStore } from "../store";

export function JobModal({ id }: { id: string }) {
  const { refresh, setModal, setView } = useStore();
  const toast = useToast();
  const [job, setJob] = useState<Job | null>(null);
  const logRef = useRef<HTMLPreElement>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const j = await api<Job>(`/api/jobs/${id}?log=16000`);
        if (!alive) return;
        const el = logRef.current;
        const atBottom = el ? el.scrollHeight - el.scrollTop - el.clientHeight < 40 : true;
        setJob(j);
        requestAnimationFrame(() => { if (atBottom && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; });
      } catch { /* задача могла быть удалена */ }
    };
    void tick();
    const t = window.setInterval(() => void tick(), 2000);
    return () => { alive = false; window.clearInterval(t); };
  }, [id]);
  const close = () => setModal(null);
  const stop = async () => {
    if (!confirm("Stop the job? The render will still download the log and delete the Pod.")) return;
    await api(`/api/jobs/${id}/stop`, { method: "POST" }); await refresh();
  };
  const del = async () => { await api(`/api/jobs/${id}`, { method: "DELETE" }); close(); await refresh(); };
  const st = job ? STATUS[job.status] : null;
  const planName = job?.result && /\.json$/.test(job.result) ? job.result.split("/").pop()!.replace(/\.json$/, "") : null;
  return (
    <Modal open onClose={close} wide
      title={<span className="flex items-center gap-2.5">{job?.title ?? "Job"} {st && <Chip tone={st.tone}>{st.label}</Chip>}</span>}
      subtitle={job ? `${job.stage}${job.shots ? ` · shot ${job.shot}/${job.shots}` : ""} · ${elapsed(job)}` : ""}
      actions={job?.status === "running" ? <Button size="sm" variant="danger" icon={<Square size={13} />} onClick={stop}>Stop</Button> : null}>
      {job?.status === "running" && <div className="mb-3"><Progress value={jobPct(job)} /></div>}
      <pre ref={logRef} className="log max-h-[420px] m-0">{job?.log || "(log is empty so far)"}</pre>
      <div className="flex flex-wrap gap-2 mt-3">
        {planName && <Button size="sm" onClick={() => setModal({ type: "plan", name: planName })}>Open plan</Button>}
        {job?.result && /\.mp4$/.test(job.result) && <Button size="sm" onClick={() => { close(); setView("films"); }}>To films</Button>}
        {job && job.status !== "running" && <Button size="sm" variant="ghost" icon={<Trash2 size={13} />} onClick={del}>Remove from list</Button>}
        {job?.status === "error" && <span className="text-bad text-[13px] self-center">{job.error}</span>}
        {job?.status === "error" && <Button size="sm" variant="ghost" className="ml-auto" onClick={() => toast("Fix the cause shown in the log, then start the job again from the Studio or Plans tab")}>What now?</Button>}
      </div>
    </Modal>
  );
}
