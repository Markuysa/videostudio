import { Download, Music2, Trash2 } from "lucide-react";
import { api, fmtAgo, fmtDur, fmtSize, type Film } from "../api";
import { Button, Chip, useToast } from "./ui";
import { useStore } from "../store";

export function FilmCard({ film, compact = false }: { film: Film; compact?: boolean }) {
  const { refresh, setModal } = useStore();
  const toast = useToast();
  const vertical = film.resolution ? (() => { const [w, h] = film.resolution.split("x").map(Number); return h > w; })() : false;
  const distilled = film.shots.filter((s) => s.pipeline === "distilled").length;
  const del = async () => {
    if (!confirm(`Delete film ${film.slug} from disk together with its clips?`)) return;
    try { await api(`/api/film/${film.slug}`, { method: "DELETE" }); toast("Film deleted"); await refresh(); } catch (e) { toast((e as Error).message, true); }
  };
  return (
    <div className={`card p-4 grid gap-4 ${vertical ? "grid-cols-[180px_1fr]" : "grid-cols-[300px_1fr]"} max-sm:grid-cols-1`}>
      <video src={`/files/${film.file}`} poster={`/api/poster/${film.slug}`} controls preload="none" playsInline
        className={`rounded-lg w-full ${vertical ? "max-h-[320px]" : "max-h-[180px]"} object-contain`} />
      <div className="min-w-0 grid gap-2.5 content-start">
        <div className="flex items-start justify-between gap-3">
          <h3 className="m-0 text-[16px] font-bold leading-tight">{film.title}</h3>
          <span className="text-muted text-[12.5px] shrink-0">{fmtAgo(film.modified)}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {film.resolution && <Chip>{film.resolution}</Chip>}
          <Chip>{fmtDur(film.seconds)}</Chip>
          {film.quality && <Chip>{film.quality}</Chip>}
          {film.shots_ok != null && <Chip tone={film.shots_failed.length ? "warn" : "good"}>{film.shots_ok} shots{film.shots_failed.length ? `, ${film.shots_failed.length} failed` : ""}</Chip>}
          {distilled > 0 && <Chip tone="warn" title="some shots were rendered with the fast pipeline after a DFR error">{distilled} distilled</Chip>}
          {film.music && <Chip>♫ music</Chip>}
          {film.captions && <Chip>💬 captions</Chip>}
          {film.minutes ? <Chip>{film.minutes} min GPU</Chip> : null}
        </div>
        {film.timeline.length > 0 && (() => {
          // подписи сцен показываем только когда для них есть место; в компактных карточках — просто полоски
          const labels = !compact && film.timeline.length + film.shots_failed.length <= 10;
          return (
            <div className={`flex ${labels ? "h-6" : "h-2.5"} rounded-md overflow-hidden border border-line`} title={`shot timeline: ${film.timeline.map((t) => t.shot).join(", ")}`}>
              {film.timeline.map((t) => {
                const s = film.shots.find((x) => x.id === t.shot);
                return <div key={t.shot} style={{ flex: Math.max(0.5, t.end - t.start) }} title={`shot ${t.shot}: ${t.start}–${t.end} s, ${s?.pipeline ?? ""} ${t.transition}`}
                  className={`grid place-items-center overflow-hidden text-[10.5px] font-bold text-[#1a1206] border-r border-black/30 last:border-r-0 min-w-[4px] ${s?.pipeline === "distilled" ? "bg-[#d0a46c]" : "bg-accent"}`}>{labels ? t.shot : ""}</div>;
              })}
              {film.shots_failed.map((id) => <div key={id} style={{ flex: 1 }} className="grid place-items-center overflow-hidden text-[10.5px] font-bold bg-bad text-white min-w-[4px]" title={`shot ${id} failed`}>{labels ? id : ""}</div>)}
            </div>
          );
        })()}
        {!compact && <div className="text-[12.5px] text-muted">{fmtSize(film.size)} · <span className="mono">{film.file}</span></div>}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <a className="inline-flex items-center gap-1.5 text-[13px] text-info hover:underline" href={`/files/${film.file}`} download><Download size={14} />download</a>
          {film.has_manifest && <Button size="sm" icon={<Music2 size={14} />} onClick={() => setModal({ type: "recut", slug: film.slug })}>Re-assemble</Button>}
          {film.recuts.length > 0 && (
            <span className="text-[12.5px] text-muted">re-cuts: {film.recuts.map((r) => <a key={r} className="text-info hover:underline mr-1.5" href={`/files/${r}`} target="_blank" rel="noreferrer">{r.split("/").pop()}</a>)}</span>
          )}
          {!compact && <Button size="sm" variant="danger" className="ml-auto" icon={<Trash2 size={14} />} onClick={del}>Delete</Button>}
        </div>
      </div>
    </div>
  );
}
