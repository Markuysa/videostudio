import { useState } from "react";
import { api, LANGS, type Job } from "../api";
import { Button, Chip, Empty, Field, Input, Select, Textarea, useToast } from "../components/ui";
import { PageHeader } from "../components/PageHeader";
import { useStore } from "../store";

export function Series() {
  const { state, refresh, setModal, setView, setPrefill } = useStore();
  const toast = useToast();
  const [desc, setDesc] = useState(""); const [name, setName] = useState(""); const [eps, setEps] = useState(6); const [lang, setLang] = useState("ru");
  const create = async () => {
    try { const j = await api<Job>("/api/series", { method: "POST", body: JSON.stringify({ description: desc, name, episodes: eps, language: lang }) }); toast("Creating the bible"); setDesc(""); await refresh(); setModal({ type: "job", id: j.id }); }
    catch (e) { toast((e as Error).message, true); }
  };
  return (
    <>
      <PageHeader title="Series" subtitle="The bible defines characters, locations and style; every episode is planned against it so the characters stay consistent." />
      <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
        <div className="card p-5 grid gap-3.5 content-start">
          <h3 className="m-0 text-[15px] font-bold">New series</h3>
          <Textarea value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What the series is about, the characters, tone, episode count…" />
          <div className="grid grid-cols-3 gap-3 max-sm:grid-cols-1">
            <Field label="Slug"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="auto" /></Field>
            <Field label="Episodes per season"><Input type="number" min={1} max={24} value={eps} onChange={(e) => setEps(Number(e.target.value))} /></Field>
            <Field label="Language"><Select value={lang} onChange={setLang} options={LANGS.map(([v, l]) => ({ value: v, label: l }))} /></Field>
          </div>
          <div><Button variant="primary" onClick={create}>Create bible</Button></div>
        </div>
        <div className="grid gap-3.5 content-start">
          {state!.series.length ? state!.series.map((s) => (
            <div key={s.slug} className="card p-5 cursor-pointer hover:border-line-2 transition" onClick={() => setModal({ type: "bible", slug: s.slug })}>
              <div className="flex items-center justify-between gap-3"><h3 className="m-0 text-[15px] font-bold">{s.title}</h3><Chip>{s.episodes}/{s.planned || "?"} episodes</Chip></div>
              <div className="text-[13px] text-muted mt-1.5">{s.premise}</div>
              <div className="flex gap-2 mt-2.5 items-center"><Chip>{s.characters} characters</Chip><span className="mono text-dim">{s.slug}</span>
                <Button size="sm" variant="primary" className="ml-auto" onClick={(e) => { e.stopPropagation(); setPrefill({ kind: "episode", series: s.slug }); setView("studio"); }}>New episode</Button></div>
            </div>
          )) : <Empty>No series yet</Empty>}
        </div>
      </div>
    </>
  );
}
