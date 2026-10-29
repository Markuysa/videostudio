import { useState } from "react";
import { api, type Job } from "../api";
import { Button, Field, Input, Modal, Select, Toggle, useToast } from "../components/ui";
import { useStore } from "../store";

export function RecutModal({ slug }: { slug: string }) {
  const { state, refresh, setModal } = useStore();
  const toast = useToast();
  const [music, setMusic] = useState(""); const [vol, setVol] = useState(""); const [caps, setCaps] = useState(false);
  const [audio, setAudio] = useState<"" | "raw" | "leveled">("");
  const film = state!.films.find((f) => f.slug === slug);
  const [lv, setLv] = useState({ dialogue: "", foley: "", model_audio: "" });
  const go = async () => {
    try { const j = await api<Job>("/api/assemble", { method: "POST", body: JSON.stringify({ film: slug, music, music_volume: vol, captions: caps, audio, ...lv }) }); toast("Re-assembly started"); await refresh(); setModal({ type: "job", id: j.id }); }
    catch (e) { toast((e as Error).message, true); }
  };
  return (
    <Modal open onClose={() => setModal(null)} title={`Re-assemble “${slug}”`} subtitle="The clips are already rendered. Only music, volume, sound stems and captions change.">
      <div className="grid gap-3.5">
        <Field label="Music"><Select value={music} onChange={setMusic} options={[{ value: "", label: "As in the plan" }, { value: "none", label: "No music" }, ...state!.library.music.map((m) => ({ value: m.file, label: m.file.split("/").pop()! }))]} /></Field>
        <Field label="Music volume (0.1–0.5)"><Input type="number" step={0.05} min={0} max={1} value={vol} onChange={(e) => setVol(e.target.value)} placeholder="as in the plan" /></Field>
        <Field label="Audio"><Select value={audio} onChange={setAudio} options={[{ value: "", label: "As in the plan" }, { value: "raw", label: "As generated", hint: "the model's sound untouched" }, { value: "leveled", label: "Leveled", hint: "scenes matched, -14 LUFS, limiter" }]} /></Field>
        {film?.sound && (
          <div className="grid grid-cols-3 gap-3">
            <Field label="Dialogue (1.0)"><Input type="number" step={0.1} min={0} max={2} value={lv.dialogue} onChange={(e) => setLv((p) => ({ ...p, dialogue: e.target.value }))} placeholder="plan" /></Field>
            <Field label="Foley (0.7)"><Input type="number" step={0.1} min={0} max={2} value={lv.foley} onChange={(e) => setLv((p) => ({ ...p, foley: e.target.value }))} placeholder="plan" /></Field>
            <Field label="Model audio (0)"><Input type="number" step={0.1} min={0} max={2} value={lv.model_audio} onChange={(e) => setLv((p) => ({ ...p, model_audio: e.target.value }))} placeholder="plan" /></Field>
          </div>
        )}
        <Toggle checked={caps} onChange={setCaps} label="Captions" />
        <div className="flex gap-2 pt-1"><Button variant="primary" onClick={go}>Assemble</Button><Button variant="ghost" onClick={() => setModal(null)}>Cancel</Button></div>
      </div>
    </Modal>
  );
}
