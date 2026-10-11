import { ToastProvider } from "./components/ui";
import { Sidebar } from "./components/Sidebar";
import { StoreProvider, useStore } from "./store";
import { Studio } from "./pages/Studio";
import { Jobs } from "./pages/Jobs";
import { Plans } from "./pages/Plans";
import { Films } from "./pages/Films";
import { Series } from "./pages/Series";
import { Sound } from "./pages/Sound";
import { SettingsPage } from "./pages/Settings";
import { JobModal } from "./modals/JobModal";
import { PlanModal } from "./modals/PlanModal";
import { RecutModal } from "./modals/RecutModal";
import { BibleModal } from "./modals/BibleModal";
import { PlayerModal } from "./modals/PlayerModal";
import { FilmModal } from "./modals/FilmModal";

function Shell() {
  const { state, view, modal } = useStore();
  const page = { studio: <Studio />, jobs: <Jobs />, plans: <Plans />, films: <Films />, series: <Series />, sound: <Sound />, settings: <SettingsPage /> }[view];
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 min-w-0 px-6 md:px-9 py-7 pb-16 max-w-[1320px]">
        {state ? page : <div className="text-dim">Loading…</div>}
      </main>
      {modal?.type === "job" && <JobModal id={modal.id} />}
      {modal?.type === "plan" && <PlanModal name={modal.name} initialTab={modal.tab} />}
      {modal?.type === "recut" && <RecutModal slug={modal.slug} />}
      {modal?.type === "bible" && <BibleModal slug={modal.slug} />}
      {modal?.type === "player" && <PlayerModal file={modal.file} title={modal.title} slug={modal.slug} />}
      {modal?.type === "film" && <FilmModal slug={modal.slug} />}
    </div>
  );
}

export const App = () => (
  <ToastProvider><StoreProvider><Shell /></StoreProvider></ToastProvider>
);
