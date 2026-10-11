import { useEffect } from "react";
import { Download, X } from "lucide-react";
import { useStore } from "../store";

/** Полноразмерный проигрыватель: вертикальные и горизонтальные ролики вписываются в экран. */
export function PlayerModal({ file, title, slug }: { file: string; title: string; slug: string }) {
  const { setModal } = useStore();
  const close = () => setModal(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  });
  return (
    <div className="fixed inset-0 z-[60] bg-black/85 backdrop-blur-sm flex flex-col" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div className="flex items-center gap-3 px-5 py-3 text-text">
        <div className="font-bold text-[16px] truncate">{title}</div>
        <span className="mono text-dim">{slug}</span>
        <a className="ml-auto inline-flex items-center gap-1.5 text-[13px] text-info hover:underline" href={`/files/${file}`} download><Download size={14} />download</a>
        <button onClick={close} className="p-2 rounded-md hover:bg-white/10 cursor-pointer" aria-label="Close"><X size={20} /></button>
      </div>
      <div className="flex-1 min-h-0 grid place-items-center px-5 pb-5" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
        <video src={`/files/${file}`} poster={`/api/poster/${slug}`} controls autoPlay playsInline
          className="rise max-h-full max-w-full rounded-lg shadow-[0_20px_60px_rgba(0,0,0,0.6)]" style={{ maxHeight: "calc(100vh - 90px)" }} />
      </div>
    </div>
  );
}
