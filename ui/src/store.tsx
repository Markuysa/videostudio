import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type State } from "./api";
import { useToast } from "./components/ui";

export type View = "studio" | "jobs" | "plans" | "films" | "series" | "sound" | "settings";
export type ModalState = { type: "job"; id: string } | { type: "plan"; name: string; tab?: "shots" | "issues" | "json" } | { type: "recut"; slug: string } | { type: "bible"; slug: string } | null;

interface Store {
  state: State | null; refresh: () => Promise<void>;
  view: View; setView: (v: View) => void;
  modal: ModalState; setModal: (m: ModalState) => void;
}
const Ctx = createContext<Store>(null!);
export const useStore = () => useContext(Ctx);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State | null>(null);
  const [view, setView] = useState<View>("studio");
  const [modal, setModal] = useState<ModalState>(null);
  const toast = useToast();
  const timer = useRef<number | undefined>(undefined);
  const failed = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const s = await api<State>("/api/state");
      setState(s);
      failed.current = false;
    } catch (e) {
      if (!failed.current) toast("No connection to the studio server: " + (e as Error).message, true);
      failed.current = true;
    }
  }, [toast]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const active = state?.jobs.some((j) => j.status === "running");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void refresh(), active ? 2500 : 8000);
    return () => window.clearTimeout(timer.current);
  }, [state, refresh]);

  return <Ctx.Provider value={{ state, refresh, view, setView, modal, setModal }}>{children}</Ctx.Provider>;
}
