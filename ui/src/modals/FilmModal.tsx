import { Download, Music2, Play, Trash2 } from "lucide-react";
import { fmtDur, fmtSize } from "../api";
import { Button, Chip, KV, Modal } from "../components/ui";
import { Timeline, useFilmActions } from "../components/FilmCard";
import { useStore } from "../store";

export function FilmModal({ slug }: { slug: string }) {
  const { state, setModal } = useStore();
  const { del, recut } = useFilmActions();
  const film = state!.films.find((f) => f.slug === slug);
  if (!film) return null;
  const close = () => setModal(null);
  const distilled = film.shots.filter((s) => s.pipeline === "distilled").length;
  return (
    <Modal open onClose={close} wide title={film.title} subtitle={<span className="mono">{film.file}</span>}
      actions={<>
        <Button size="sm" variant="primary" icon={<Play size={13} fill="currentColor" />} onClick={() => setModal({ type: "player", file: film.file, title: film.title, slug: film.slug })}>Play</Button>
        {film.has_manifest && <Button size="sm" icon={<Music2 size={13} />} onClick={() => recut(film)}>Re-assemble</Button>}
        <a className="inline-flex items-center gap-2 text-[13px] px-2.5 py-1.5 rounded-md border border-line-2 hover:bg-panel-2" href={`/files/${film.file}`} download><Download size={13} />Download</a>
        <Button size="sm" variant="danger" icon={<Trash2 size={13} />} onClick={async () => { await del(film); close(); }}>Delete</Button>
      </>}>
      <div className="grid grid-cols-[1fr_1fr] gap-6 max-md:grid-cols-1">
        <KV rows={[
          ["Resolution", film.resolution ?? "—"], ["Running time", fmtDur(film.seconds)], ["Quality", film.quality ?? "—"],
          ["Shots", <span>{film.shots_ok ?? "—"} ok{film.shots_failed.length ? <span className="text-bad"> · {film.shots_failed.length} failed ({film.shots_failed.join(", ")})</span> : null}{distilled ? <span className="text-warn"> · {distilled} distilled</span> : null}</span>],
          ["Audio", film.sound ? <span>sound studio · {film.sound.lines} lines{film.sound.lipsync.length ? `, lip-sync in ${film.sound.lipsync.join(", ")}` : ""} · Foley {film.sound.foley.length}/{film.shots.length}{film.sound.score ? " · score" : ""}</span>
            : film.audio === "leveled" ? "leveled (scenes matched, -14 LUFS)" : "raw (model sound untouched)"],
          ["Loop", film.loop ? (film.loop_closed ? <Chip tone="good">closed on the first frame</Chip> : <Chip tone="warn">not closed</Chip>) : "no"],
          ["Extras", <span>{film.captions ? "captions " : ""}{film.music ? "music " : ""}{!film.captions && !film.music ? "—" : ""}</span>],
          ["GPU time", film.minutes ? `${film.minutes} min` : "—"], ["File", fmtSize(film.size)],
          ["Plan", film.plan ? <button className="text-info hover:underline cursor-pointer" onClick={() => setModal({ type: "plan", name: film.plan! })}>{film.plan}.json</button> : "—"],
        ]} />
        <div>
          <div className="label mb-2">Shot timeline</div>
          <Timeline film={film} labels={film.timeline.length <= 12} />
          {film.recuts.length > 0 && (<>
            <div className="label mt-4 mb-2">Re-cuts</div>
            <div className="grid gap-1 text-[13px]">{film.recuts.map((r) => (
              <div key={r} className="flex items-center gap-2"><span className="mono truncate">{r.split("/").pop()}</span>
                <button className="text-info hover:underline cursor-pointer" onClick={() => setModal({ type: "player", file: r, title: `${film.title} · ${r.split("/").pop()}`, slug: film.slug })}>play</button>
                <a className="text-info hover:underline" href={`/files/${r}`} download>download</a></div>
            ))}</div>
          </>)}
        </div>
      </div>
      {film.shots.length > 0 && (<>
        <div className="label mt-5 mb-2">Per-shot report</div>
        <div className="card overflow-hidden">
          <table className="table w-full text-[13.5px]">
            <thead><tr><th>Shot</th><th>Pipeline</th><th>Size</th><th>Render</th><th>Continuity</th>{film.sound && <th>Sound</th>}<th>Timeline</th></tr></thead>
            <tbody>{film.shots.map((s) => {
              const t = film.timeline.find((x) => x.shot === s.id);
              return (
                <tr key={s.id}>
                  <td className="mono font-bold text-accent">{s.id}</td>
                  <td><Chip tone={s.pipeline === "dfr" ? "good" : "warn"}>{s.pipeline}</Chip>{s.cached && <Chip className="ml-1.5">cached</Chip>}</td>
                  <td className="text-muted">{s.size ?? "—"}</td>
                  <td className="text-muted">{s.seconds_render != null ? `${s.seconds_render} s` : "—"}</td>
                  <td className="text-muted">{s.continuity ? "from previous frame" : s.loop_closed ? "closes the loop" : "—"}</td>
                  {film.sound && <td className="text-muted">{[s.lipsync ? "lip-sync" : "", s.foley ? "Foley" : "model audio"].filter(Boolean).join(" · ")}</td>}
                  <td className="text-muted">{t ? `${t.start}–${t.end} s · ${t.transition}` : "—"}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      </>)}
    </Modal>
  );
}
