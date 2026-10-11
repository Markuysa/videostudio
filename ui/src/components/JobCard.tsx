import { elapsed, type Job } from "../api";
import { Chip, Progress } from "./ui";
import { useStore } from "../store";

export const STATUS: Record<Job["status"], { label: string; tone: "default" | "accent" | "good" | "bad" | "warn" }> = {
  queued: { label: "queued", tone: "default" }, running: { label: "running", tone: "accent" }, done: { label: "done", tone: "good" },
  error: { label: "error", tone: "bad" }, stopped: { label: "stopped", tone: "warn" },
};

export function jobPct(j: Job): number | null {
  if (!j.shots) return null;
  return Math.round((100 * ((j.shot ?? 0) - (j.status === "running" ? 1 : 0))) / j.shots);
}

export function JobCard({ job }: { job: Job }) {
  const { setModal } = useStore();
  const st = STATUS[job.status];
  return (
    <div onClick={() => setModal({ type: "job", id: job.id })} className="card p-4 cursor-pointer hover:border-line-2 transition grid gap-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="font-semibold truncate">{job.title}</div>
        <Chip tone={st.tone}>{job.status === "running" && <span className="pulse w-1.5 h-1.5 rounded-full bg-accent" />}{st.label}</Chip>
      </div>
      {job.status === "running" && <Progress value={jobPct(job)} />}
      <div className="flex justify-between text-[12.5px] text-muted">
        <span>{job.stage}{job.shots ? ` · shot ${job.shot}/${job.shots}` : ""}</span>
        <span>{elapsed(job)}</span>
      </div>
      {job.status === "error" && job.error && <div className="text-[13px] text-bad">{job.error}</div>}
    </div>
  );
}
