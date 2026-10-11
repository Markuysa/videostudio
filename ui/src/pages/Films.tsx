import { Empty } from "../components/ui";
import { FilmCard } from "../components/FilmCard";
import { useStore } from "../store";

export function Films() {
  const { state } = useStore();
  const films = state!.films;
  return (
    <>
      <h1 className="text-[28px] font-extrabold tracking-tight m-0">Films</h1>
      <p className="text-muted mt-1 mb-6">Finished films with a per-shot report. Re-assembly changes music and captions without a GPU (needs ffmpeg).</p>
      {films.length ? <div className="grid gap-4">{films.map((f) => <FilmCard key={f.slug} film={f} />)}</div> : <Empty>No films yet</Empty>}
    </>
  );
}
