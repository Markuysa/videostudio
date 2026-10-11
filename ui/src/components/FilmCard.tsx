import { Download, Info, Music2, Play, Repeat, Trash2 } from "lucide-react";
import { api, fmtAgo, fmtDur, fmtSize, type Film } from "../api";
import { Button, Chip, useToast } from "./ui";
import { useStore } from "../store";

export function Thumb({ film, className = "" }: { film: Film; className?: string }) {
  const { setModal } = useStore();
  return (
    <button type="button" onClick={() => setModal({ type: "player", file: film.file, title: film.title, slug: film.slug })}
      className={`relative rounded-lg overflow-hidden bg-black grid place-items-center cursor-pointer group border-0 p-0 ${className}`}
      title={`Play ${film.title}`} aria-label={`Play ${film.title}`}>
      <img src={`/api/poster/${film.slug}`} alt="" className="w-full h-full object-cover opacity-90 group-hover:opacity-100 group-hover:scale-[1.03] transition duration-300"
        onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
      <span className="absolute inset-0 bg-gradient-to-t from-black/50 via-transparent to-transparent" />
      <span className="absolute inset-0 grid place-items-center">
        <span className="w-12 h-12 rounded-full bg-black/55 border border-white/30 backdrop-blur grid place-items-center text-white group-hover:scale-110 group-hover:bg-accent group-hover:text-[#1a1206] transition">
          <Play size={20} className="ml-0.5" fill="currentColor" />
        </span>
      </span>
      {film.seconds != null && <span className="absolute right-2 bottom-2 text-[11.5px] font-semibold bg-black/65 text-white rounded px-1.5 py-0.5">{fmtDur(film.seconds)}</span>}
      {film.loop && <span className="absolute left-2 top-2 inline-flex items-center gap-1 text-[11px] font-semibold bg-black/60 text-white rounded px-1.5 py-0.5"><Repeat size={10} />loop</span>}
    </button>
  );
}

export function Timeline({ film, labels }: { film: Film; labels: boolean }) {
  if (!film.timeline.length) return null;
  return (
    <div className={`flex ${labels ? "h-6" : "h-2"} rounded-md overflow-hidden border border-line`} title={`shot timeline: ${film.timeline.map((t) => t.shot).join(", ")}`}>
      {film.timeline.map((t) => {
        const s = film.shots.find((x) => x.id === t.shot);
        return <div key={t.shot} style={{ flex: Math.max(0.5, t.end - t.start) }} title={`shot ${t.shot}: ${t.start}–${t.end} s, ${s?.pipeline ?? ""} ${t.transition}`}
          className={`grid place-items-center overflow-hidden text-[10.5px] font-bold text-[#1a1206] border-r border-black/30 last:border-r-0 min-w-[4px] ${s?.pipeline === "distilled" ? "bg-[#d0a46c]" : "bg-accent"}`}>{labels ? t.shot : ""}</div>;
      })}
      {film.shots_failed.map((id) => <div key={id} style={{ flex: 1 }} className="grid place-items-center overflow-hidden text-[10.5px] font-bold bg-bad text-white min-w-[4px]" title={`shot ${id} failed`}>{labels ? id : ""}</div>)}
    </div>
  );
}

export function useFilmActions() {
  const { refresh, setModal } = useStore();
  const toast = useToast();
  const del = async (film: Film) => {
    if (!confirm(`Delete film ${film.slug} from disk together with its clips?`)) return;
    try { await api(`/api/film/${film.slug}`, { method: "DELETE" }); toast("Film deleted"); await refresh(); } catch (e) { toast((e as Error).message, true); }
  };
  return { del, recut: (film: Film) => setModal({ type: "recut", slug: film.slug }), details: (film: Film) => setModal({ type: "film", slug: film.slug }) };
}

/** Компактная строка для главной. */
export function FilmCard({ film }: { film: Film }) {
  const { recut, details } = useFilmActions();
  const distilled = film.shots.filter((s) => s.pipeline === "distilled").length;
  return (
    <div className="card p-4 grid grid-cols-[220px_1fr] gap-4 max-sm:grid-cols-1 min-h-[156px]">
      <Thumb film={film} className="w-[220px] h-[124px] max-sm:w-full" />
      <div className="min-w-0 grid gap-2.5 content-start">
        <div className="flex items-start justify-between gap-3">
          <h3 className="m-0 text-[16px] font-bold leading-tight truncate">{film.title}</h3>
          <span className="text-muted text-[12.5px] shrink-0">{fmtAgo(film.modified)}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {film.resolution && <Chip>{film.resolution}</Chip>}
          {film.shots_ok != null && <Chip tone={film.shots_failed.length ? "warn" : "good"}>{film.shots_ok} shots{film.shots_failed.length ? `, ${film.shots_failed.length} failed` : ""}</Chip>}
          {distilled > 0 && <Chip tone="warn">{distilled} distilled</Chip>}
          {film.minutes ? <Chip>{film.minutes} min GPU</Chip> : null}
        </div>
        <Timeline film={film} labels={false} />
        <div className="flex flex-wrap items-center gap-2">
          <a className="inline-flex items-center gap-1.5 text-[13px] text-info hover:underline" href={`/files/${film.file}`} download><Download size={14} />download</a>
          {film.has_manifest && <Button size="sm" icon={<Music2 size={14} />} onClick={() => recut(film)}>Re-assemble</Button>}
          <Button size="sm" variant="link" icon={<Info size={14} />} onClick={() => details(film)}>Details</Button>
        </div>
      </div>
    </div>
  );
}

/** Постер-карточка для медиатеки. */
export function FilmTile({ film }: { film: Film }) {
  const { del, recut, details } = useFilmActions();
  const distilled = film.shots.filter((s) => s.pipeline === "distilled").length;
  return (
    <div className="card overflow-hidden grid grid-rows-[auto_1fr] hover:border-line-2 transition">
      <Thumb film={film} className="w-full aspect-video rounded-none" />
      <div className="p-4 grid gap-2.5 content-start">
        <div className="flex items-start justify-between gap-3">
          <h3 className="m-0 text-[15.5px] font-bold leading-tight line-clamp-2 cursor-pointer hover:text-accent" onClick={() => details(film)}>{film.title}</h3>
          <span className="text-muted text-[12px] shrink-0 pt-0.5">{fmtAgo(film.modified)}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {film.resolution && <Chip>{film.resolution}</Chip>}
          {film.quality && <Chip>{film.quality.split(" ")[0]}</Chip>}
          {film.shots_ok != null && <Chip tone={film.shots_failed.length ? "warn" : "good"}>{film.shots_ok} shots</Chip>}
          {distilled > 0 && <Chip tone="warn" title="rendered with the fast pipeline after a DFR error">{distilled} distilled</Chip>}
          {film.captions && <Chip>💬</Chip>}
          {film.music && <Chip>♫</Chip>}
        </div>
        <Timeline film={film} labels={false} />
        <div className="flex items-center gap-1.5 pt-1.5 border-t border-line text-[12.5px] text-muted">
          <span>{fmtSize(film.size)}{film.minutes ? ` · ${film.minutes} min GPU` : ""}</span>
          <span className="ml-auto flex items-center gap-1">
            <a className="p-1.5 rounded-md hover:bg-white/5 text-muted hover:text-text" href={`/files/${film.file}`} download title="Download"><Download size={15} /></a>
            {film.has_manifest && <button className="p-1.5 rounded-md hover:bg-white/5 text-muted hover:text-text cursor-pointer" onClick={() => recut(film)} title="Re-assemble"><Music2 size={15} /></button>}
            <button className="p-1.5 rounded-md hover:bg-white/5 text-muted hover:text-text cursor-pointer" onClick={() => details(film)} title="Details"><Info size={15} /></button>
            <button className="p-1.5 rounded-md hover:bg-bad/10 text-muted hover:text-bad cursor-pointer" onClick={() => del(film)} title="Delete"><Trash2 size={15} /></button>
          </span>
        </div>
      </div>
    </div>
  );
}
