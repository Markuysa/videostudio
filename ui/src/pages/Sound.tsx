import { RefreshCw, Upload } from "lucide-react";
import { api, fmtDur, type LibraryEntry } from "../api";
import { Button, Empty, useToast } from "../components/ui";
import { useStore } from "../store";

export function Sound() {
  const { state, refresh } = useStore();
  const toast = useToast();
  const lib = state!.library;
  const upload = async (kind: "music" | "sfx", files: FileList | null) => {
    if (!files) return;
    for (const f of Array.from(files)) {
      const fd = new FormData(); fd.append("file", f, f.name);
      try { await api(`/api/assets/upload?kind=${kind}`, { method: "POST", body: fd }); toast(`Uploaded: ${f.name}`); } catch (e) { toast((e as Error).message, true); }
    }
    await refresh();
  };
  const List = ({ items, kind }: { items: LibraryEntry[]; kind: string }) => items.length ? (
    <table className="table w-full text-[13.5px]">
      <thead><tr><th>File</th><th>Tags</th><th>Length</th><th></th></tr></thead>
      <tbody>{items.map((e) => (
        <tr key={e.file}><td className="mono">{e.file.split("/").pop()}</td><td className="text-muted text-[12.5px]">{e.tags.join(", ")}{e.mood ? <i> · {e.mood}</i> : null}</td><td>{e.seconds ? fmtDur(e.seconds) : "—"}</td>
          <td><audio src={`/files/${e.file}`} controls preload="none" className="h-7 w-52" /></td></tr>
      ))}</tbody>
    </table>
  ) : <Empty>Empty. Upload files or put them into assets/{kind}/</Empty>;
  const Panel = ({ title, kind, items }: { title: string; kind: "music" | "sfx"; items: LibraryEntry[] }) => (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="m-0 text-[15px] font-bold">{title}</h3>
        <label className="inline-flex items-center gap-2 text-[13px] bg-panel-2 border border-line rounded-md px-3 py-1.5 cursor-pointer hover:bg-line-2"><Upload size={14} />Upload<input type="file" accept="audio/*" multiple hidden onChange={(e) => void upload(kind, e.target.files)} /></label>
      </div>
      <List items={items} kind={kind} />
    </div>
  );
  return (
    <>
      <h1 className="text-[28px] font-extrabold tracking-tight m-0">Sound</h1>
      <p className="text-muted mt-1 mb-6">Music and effects the planner picks by tags. Tags come from file names and can be edited in assets/index.json.</p>
      <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1"><Panel title="Music" kind="music" items={lib.music} /><Panel title="Effects" kind="sfx" items={lib.sfx} /></div>
      <div className="flex items-center gap-3 mt-4"><Button icon={<RefreshCw size={14} />} onClick={async () => { await api("/api/assets/reindex", { method: "POST" }); toast("Index updated"); await refresh(); }}>Re-index</Button><span className="text-muted text-[13px]">after copying files into the folders manually</span></div>
    </>
  );
}
