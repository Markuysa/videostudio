import { useState } from "react";
import { Sparkles } from "lucide-react";
import { api } from "../api";
import { Button, Field, Textarea, useToast } from "./ui";

const fields = [
  ["subject", "Subject & appearance"], ["setting", "Location & time"],
  ["action", "Action & progression"], ["camera", "Framing & camera"],
  ["lighting", "Light & style"], ["sound", "Sound & dialogue"],
  ["continuity", "What stays consistent"],
] as const;
type Brief = Record<typeof fields[number][0], string> & { assumptions: string[]; questions: string[] };

export function PromptAssistant({ context, onApply }: {
  context: Record<string, unknown>; onApply: (text: string) => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [source, setSource] = useState("");
  const snapshot = JSON.stringify(context);
  const stale = !!brief && source !== snapshot;
  const generate = async () => {
    setBusy(true);
    try {
      const result = await api<Brief>("/api/prompt-assistant", { method: "POST", body: snapshot });
      setBrief(result); setSource(snapshot);
    } catch (e) { toast((e as Error).message, true); }
    finally { setBusy(false); }
  };
  return <div className="grid gap-3">
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="ghost" icon={<Sparkles size={16} />} disabled={busy || !String(context.request || "").trim()} onClick={generate}>
        {busy ? "Developing direction…" : brief ? "Regenerate direction" : "Help develop the idea"}
      </Button>
      <span className="text-xs text-muted">Uses your configured writing assistant</span>
    </div>
    {brief && <div className="grid gap-3 rounded-xl border border-line p-4">
      <p className="text-sm text-muted m-0">Review these suggestions before applying. The studio will turn the direction into LTX-2.5 prompts for each shot.</p>
      {stale && <p role="status" className="text-sm text-muted">The idea or settings changed. Regenerate the suggestions to match.</p>}
      <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
        {fields.map(([key, label]) => <Field key={key} label={label}>
          <Textarea rows={3} value={brief[key]} onChange={e => setBrief({ ...brief, [key]: e.target.value })} />
        </Field>)}
      </div>
      {!!brief.assumptions.length && <div className="text-sm"><strong>Suggested additions — check these</strong><ul className="list-disc pl-5">{brief.assumptions.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
      {!!brief.questions.length && <div className="text-sm"><strong>To clarify — edit the fields above</strong><ul className="list-disc pl-5">{brief.questions.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
      <div className="flex gap-2">
        <Button variant="primary" disabled={busy || stale} onClick={() => {
          onApply(fields.filter(([key]) => brief[key].trim()).map(([key, label]) => `${label}: ${brief[key].trim()}`).join("\n"));
          toast("Direction applied to the next script");
        }}>Apply direction</Button>
        <Button variant="ghost" disabled={busy} onClick={() => setBrief(null)}>Close</Button>
      </div>
    </div>}
  </div>;
}
