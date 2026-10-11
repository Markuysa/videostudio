import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Empty, Input, Segmented, Stat } from "../components/ui";
import { FilmTile } from "../components/FilmCard";
import { PageHeader } from "../components/PageHeader";
import { useStore } from "../store";

type Sort = "newest" | "longest" | "title";
export function Films() {
  const { state } = useStore();
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("newest");
  const [orient, setOrient] = useState<"all" | "vertical" | "horizontal">("all");
  const films = state!.films;
  const shown = useMemo(() => films
    .filter((f) => !q.trim() || `${f.title} ${f.slug}`.toLowerCase().includes(q.toLowerCase()))
    .filter((f) => { if (orient === "all" || !f.resolution) return true; const [w, h] = f.resolution.split("x").map(Number); return orient === "vertical" ? h > w : w >= h; })
    .sort((a, b) => sort === "newest" ? b.modified - a.modified : sort === "longest" ? (b.seconds ?? 0) - (a.seconds ?? 0) : a.title.localeCompare(b.title)),
    [films, q, sort, orient]);
  const totalSec = films.reduce((a, f) => a + (f.seconds ?? 0), 0);
  const totalGpu = films.reduce((a, f) => a + (f.minutes ?? 0), 0);
  return (
    <>
      <PageHeader title="Films" subtitle="Everything the studio has rendered. Click a poster to play, open details for the per-shot report, re-assemble to change music, captions or audio mode without a GPU." />
      <div className="card p-5 mb-5 flex flex-wrap items-center gap-8">
        <Stat value={films.length} label="films" />
        <Stat value={`${Math.round(totalSec / 60)} min`} label="footage" />
        <Stat value={`${totalGpu} min`} label="GPU time" />
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <div className="relative w-[240px]"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-dim" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" className="pl-9 py-2" /></div>
          <Segmented size="sm" value={orient} onChange={setOrient} options={[{ value: "all", label: "All" }, { value: "vertical", label: "9:16" }, { value: "horizontal", label: "16:9" }]} />
          <Segmented size="sm" value={sort} onChange={setSort} options={[{ value: "newest", label: "Newest" }, { value: "longest", label: "Longest" }, { value: "title", label: "A–Z" }]} />
        </div>
      </div>
      {shown.length ? <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(300px,1fr))]">{shown.map((f) => <FilmTile key={f.slug} film={f} />)}</div>
        : <Empty>{films.length ? "Nothing matches" : "No films yet. Shoot the first one on the Studio tab."}</Empty>}
    </>
  );
}
