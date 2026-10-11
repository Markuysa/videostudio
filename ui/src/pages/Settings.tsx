import { useEffect, useState } from "react";
import { api } from "../api";
import { Button, Chip, KV, Textarea, useToast } from "../components/ui";
import { PageHeader } from "../components/PageHeader";
import { useStore } from "../store";

export function SettingsPage() {
  const { state } = useStore();
  const toast = useToast();
  const c = state!.config;
  const [prefs, setPrefs] = useState(state!.prefs);
  const [doctor, setDoctor] = useState<string[] | null>(null);
  useEffect(() => setPrefs(state!.prefs), [state]);
  return (
    <>
      <PageHeader title="Settings" subtitle={<>Keys and parameters live in <span className="mono">{c.config_path}</span>. Here: environment check and standing planner preferences.</>} />
      <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
        <div className="card p-5">
          <h3 className="m-0 mb-3 text-[15px] font-bold">Environment</h3>
          <KV rows={[
            ["LLM", <span className="flex flex-wrap items-center gap-2">{c.llm_effective} · {c.llm_model} {c.has_anthropic ? <Chip tone="good">Anthropic key present</Chip> : <Chip tone="warn">no ANTHROPIC_API_KEY — local Ollama, lower script quality</Chip>}</span>],
            ["RunPod", <span className="flex flex-wrap items-center gap-2">{c.has_runpod ? <Chip tone="good">configured</Chip> : <Chip tone="bad">not configured</Chip>} · default quality <b>{c.quality}</b> · limit {c.max_hours} h</span>],
            ["GPUs (fast)", <span className="text-[13px]">{(c.gpu_types ?? []).join(", ")}</span>],
            ["ffmpeg", c.ffmpeg ? <Chip tone="good">yes</Chip> : <Chip tone="warn">no — re-assembly unavailable (brew install ffmpeg)</Chip>],
            ["Voice-over", c.has_elevenlabs ? <Chip tone="good">ElevenLabs configured</Chip> : <Chip>no (narration in the plan stays as text)</Chip>],
          ]} />
          <div className="mt-4"><Button size="sm" onClick={async () => setDoctor((await api<{ lines: string[] }>("/api/doctor")).lines)}>Full diagnostics</Button></div>
          {doctor && <pre className="log mt-3">{doctor.join("\n")}</pre>}
        </div>
        <div className="card p-5 grid gap-3 content-start">
          <h3 className="m-0 text-[15px] font-bold">Planner preferences</h3>
          <p className="m-0 text-muted text-[13px]">Applied to every plan. For example: “fewer close-ups”, “always end on a wide shot”, “no dissolves”, “photoreal, never 3D-animated”.</p>
          <Textarea value={prefs} onChange={(e) => setPrefs(e.target.value)} className="min-h-[220px]" />
          <div><Button variant="primary" onClick={async () => { await api("/api/prefs", { method: "PUT", body: JSON.stringify({ text: prefs }) }); toast("Saved"); }}>Save</Button></div>
        </div>
      </div>
    </>
  );
}
