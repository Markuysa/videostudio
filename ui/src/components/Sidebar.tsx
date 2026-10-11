import { Clapperboard, Clock, FileText, Film, Music, Settings, Tv } from "lucide-react";
import { useStore, type View } from "../store";

const NAV: { view: View; label: string; icon: React.ReactNode }[] = [
  { view: "studio", label: "Studio", icon: <Clapperboard size={17} /> },
  { view: "jobs", label: "Jobs", icon: <Clock size={17} /> },
  { view: "plans", label: "Plans", icon: <FileText size={17} /> },
  { view: "films", label: "Films", icon: <Film size={17} /> },
  { view: "series", label: "Series", icon: <Tv size={17} /> },
  { view: "sound", label: "Sound", icon: <Music size={17} /> },
  { view: "settings", label: "Settings", icon: <Settings size={17} /> },
];

export function Sidebar() {
  const { state, view, setView } = useStore();
  const running = state?.jobs.filter((j) => j.status === "running").length ?? 0;
  const c = state?.config;
  const Dot = ({ on, bad }: { on: boolean; bad?: boolean }) => (
    <span className={`inline-block w-2 h-2 rounded-full mr-2 ${on ? "bg-good shadow-[0_0_8px_var(--color-good)]" : bad ? "bg-bad" : "bg-dim"}`} />
  );
  return (
    <aside className="sticky top-0 h-screen w-[232px] shrink-0 bg-bg-2 border-r border-line p-4 flex flex-col gap-1 max-md:hidden">
      <div className="flex items-center gap-2.5 px-2 pt-1 pb-5">
        <div className="w-9 h-9 rounded-[10px] bg-gradient-to-br from-accent to-accent-2 grid place-items-center text-[#1a1206]"><Clapperboard size={18} /></div>
        <div className="font-extrabold text-[17px] tracking-tight">Film Studio</div>
      </div>
      {NAV.map((n) => (
        <button key={n.view} onClick={() => setView(n.view)}
          className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-left font-medium transition cursor-pointer ${view === n.view ? "bg-panel-2 text-text" : "text-muted hover:bg-panel hover:text-text"}`}>
          <span className="text-muted">{n.icon}</span>
          <span>{n.label}</span>
          {n.view === "jobs" && running > 0 && <span className="ml-auto bg-accent text-[#1a1206] text-[11px] font-extrabold rounded-full px-2 py-px">{running}</span>}
        </button>
      ))}
      <div className="mt-auto text-[12px] text-dim px-3 leading-relaxed">
        {c && (<>
          <div><Dot on={c.has_runpod} bad={!c.has_runpod} />RunPod {c.has_runpod ? "configured" : "not configured"}</div>
          <div><Dot on={c.llm_effective === "anthropic"} />LLM: {c.llm_model}</div>
          <div><Dot on={c.ffmpeg} bad={!c.ffmpeg} />ffmpeg {c.ffmpeg ? "yes" : "no"}</div>
        </>)}
      </div>
    </aside>
  );
}
