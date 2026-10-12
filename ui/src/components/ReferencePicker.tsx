import { useRef, useState } from "react";
import { ImagePlus, Loader2, X } from "lucide-react";
import { api, type RefItem, type RefRole } from "../api";
import { useToast } from "./ui";

const ROLES: { value: RefRole; label: string; hint: string }[] = [
  { value: "style", label: "Style", hint: "look only: palette, light, lens, texture" },
  { value: "frame", label: "Shot frame", hint: "becomes the first frame of one shot" },
  { value: "opening", label: "Opening", hint: "the first frame of the film" },
];

export async function uploadImages(files: FileList | File[]): Promise<RefItem[]> {
  const fd = new FormData();
  Array.from(files).forEach((f) => fd.append("file", f, f.name));
  const res = await api<Omit<RefItem, "role">[]>("/api/refs/upload", { method: "POST", body: fd });
  return res.map((r) => ({ ...r, role: "style" as RefRole }));
}

/** Фото-референсы для нового фильма: перетащить, выбрать роль каждой картинки. */
export function ReferencePicker({ value, onChange, max = 8 }: { value: RefItem[]; onChange: (v: RefItem[]) => void; max?: number }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const add = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files).filter((f) => /\.(jpe?g|png|webp)$/i.test(f.name)).slice(0, Math.max(0, max - value.length));
    if (!list.length) { toast("Reference images must be jpg, png or webp (up to 8)", true); return; }
    setBusy(true);
    try {
      const added = await uploadImages(list);
      const next = [...value];
      for (const r of added) if (!next.some((x) => x.file === r.file)) next.push(r);
      onChange(next);
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const setRole = (i: number, role: RefRole) => onChange(value.map((r, k) => k === i ? { ...r, role } : (role === "opening" && r.role === "opening" ? { ...r, role: "frame" } : r)));
  return (
    <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); void add(e.dataTransfer.files); }}
      className={`rounded-lg border border-dashed transition ${over ? "border-accent bg-accent/5" : "border-line-2"} ${value.length ? "p-3" : "px-3 py-2.5"}`}>
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" multiple hidden onChange={(e) => { void add(e.target.files); e.target.value = ""; }} />
      {value.length === 0 ? (
        <button type="button" onClick={() => input.current?.click()} className="w-full flex items-center gap-3 text-left text-muted hover:text-text cursor-pointer">
          {busy ? <Loader2 size={18} className="animate-spin" /> : <ImagePlus size={18} />}
          <span className="text-[13.5px]"><b className="text-text font-semibold">Reference photos</b> · drop or click — the film takes their look, and any photo can be the first frame of a shot</span>
        </button>
      ) : (
        <div className="grid gap-2.5">
          <div className="flex flex-wrap gap-2.5">
            {value.map((r, i) => (
              <div key={r.file} className="w-[148px] rounded-lg overflow-hidden border border-line bg-bg-2">
                <div className="relative h-[92px] bg-black">
                  {r.url && <img src={r.url} alt="" className="w-full h-full object-cover" />}
                  {r.role === "opening" && <span className="absolute left-1.5 top-1.5 text-[10.5px] font-bold bg-accent text-[#1a1206] rounded px-1.5 py-px">FIRST FRAME</span>}
                  <button type="button" onClick={() => onChange(value.filter((_, k) => k !== i))} title="Remove"
                    className="absolute right-1 top-1 w-6 h-6 rounded-full bg-black/60 text-white grid place-items-center hover:bg-bad cursor-pointer"><X size={13} /></button>
                </div>
                <div className="grid grid-cols-3 text-[10.5px] font-semibold">
                  {ROLES.map((ro) => (
                    <button key={ro.value} type="button" title={ro.hint} onClick={() => setRole(i, ro.value)}
                      className={`py-1.5 cursor-pointer transition ${r.role === ro.value ? "bg-accent/15 text-accent" : "text-muted hover:text-text hover:bg-white/5"}`}>
                      {ro.value === "frame" ? "Frame" : ro.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {value.length < max && (
              <button type="button" onClick={() => input.current?.click()}
                className="w-[148px] h-[121px] rounded-lg border border-dashed border-line-2 grid place-items-center text-muted hover:text-text hover:border-accent cursor-pointer">
                {busy ? <Loader2 size={20} className="animate-spin" /> : <span className="grid place-items-center gap-1 text-[12px]"><ImagePlus size={20} />Add</span>}
              </button>
            )}
          </div>
          <div className="text-[12px] text-dim">
            Style — only the look (palette, light, lens, texture). Frame — the photo becomes the first frame of one shot. Opening — the first frame of the film.
            Frame and opening shots are capped at 5 s in high quality; the format follows the opening photo unless you set it.
          </div>
        </div>
      )}
    </div>
  );
}
