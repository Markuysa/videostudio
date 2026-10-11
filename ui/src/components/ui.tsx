import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown, X } from "lucide-react";

/* ---------- toasts ---------- */
type Toast = { id: number; text: string; bad?: boolean };
const ToastCtx = createContext<(text: string, bad?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = (text: string, bad = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, bad }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), bad ? 6500 : 3500);
  };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed right-5 bottom-5 z-[80] flex flex-col gap-2 max-w-[420px]">
        {toasts.map((t) => (
          <div key={t.id} className={`rise card px-4 py-3 text-[14px] ${t.bad ? "border-bad/60" : ""}`}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------- primitives ---------- */
type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "link"; size?: "sm" | "md" | "lg"; icon?: ReactNode;
};
export function Button({ variant = "secondary", size = "md", icon, className = "", children, ...rest }: BtnProps) {
  const v = {
    primary: "bg-gradient-to-br from-accent to-accent-2 text-[#1a1206] font-semibold hover:brightness-110 shadow-[0_6px_20px_rgba(242,179,91,0.25)]",
    secondary: "bg-panel-2 text-text hover:bg-line-2 border border-line",
    ghost: "bg-transparent text-text border border-line-2 hover:bg-panel-2",
    danger: "bg-transparent text-bad border border-bad/40 hover:bg-bad/10",
    link: "bg-transparent text-muted hover:text-text px-1",
  }[variant];
  const s = { sm: "text-[13px] px-2.5 py-1.5 rounded-md", md: "text-[14px] px-3.5 py-2.5 rounded-md", lg: "text-[15.5px] px-6 py-3 rounded-lg" }[size];
  return (
    <button className={`inline-flex items-center gap-2 transition disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer ${v} ${s} ${className}`} {...rest}>
      {icon}{children}
    </button>
  );
}

export function Chip({ tone = "default", children, title, className = "" }: { tone?: "default" | "good" | "bad" | "warn" | "accent" | "info"; children: ReactNode; title?: string; className?: string }) {
  const t = {
    default: "text-muted border-line-2", good: "text-good border-good/40", bad: "text-bad border-bad/40",
    warn: "text-warn border-warn/40", accent: "text-accent border-accent/45", info: "text-info border-info/40",
  }[tone];
  return <span title={title} className={`inline-flex items-center gap-1.5 text-[12px] px-2.5 py-0.5 rounded-full border bg-bg-2 whitespace-nowrap ${t} ${className}`}>{children}</span>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="text-[12px] text-dim">{hint}</span>}
    </label>
  );
}

export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={`input ${p.className ?? ""}`} />;
export const Textarea = (p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={`input resize-y min-h-[90px] leading-relaxed ${p.className ?? ""}`} />;

/* ---------- select ---------- */
export type Option<T extends string = string> = { value: T; label: string; hint?: string };
export function Select<T extends string>({ value, options, onChange, className = "" }: { value: T; options: Option<T>[]; onChange: (v: T) => void; className?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", h); document.addEventListener("keydown", k);
    return () => { document.removeEventListener("mousedown", h); document.removeEventListener("keydown", k); };
  }, [open]);
  const cur = options.find((o) => o.value === value) ?? options[0];
  return (
    <div ref={ref} className={`relative ${className}`}>
      <button type="button" onClick={() => setOpen((o) => !o)}
        className={`input flex items-center justify-between gap-2 text-left cursor-pointer ${open ? "border-accent shadow-[0_0_0_3px_rgba(242,179,91,0.16)]" : ""}`}>
        <span className="truncate">{cur?.label}</span>
        <ChevronDown size={16} className={`shrink-0 text-muted transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="rise absolute z-40 left-0 right-0 mt-1.5 card p-1.5 max-h-72 overflow-auto">
          {options.map((o) => (
            <div key={o.value} onClick={() => { onChange(o.value); setOpen(false); }}
              className={`flex items-start justify-between gap-2 px-2.5 py-2 rounded-md cursor-pointer hover:bg-white/5 ${o.value === value ? "bg-accent/10 text-accent" : ""}`}>
              <div className="flex flex-col"><span>{o.label}</span>{o.hint && <small className="text-muted text-[12px]">{o.hint}</small>}</div>
              {o.value === value && <Check size={15} className="mt-0.5 shrink-0" />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- segmented ---------- */
export function Segmented<T extends string | number>({ value, options, onChange, full = false, size = "md" }:
  { value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; full?: boolean; size?: "sm" | "md" }) {
  return (
    <div className={`inline-flex gap-1 bg-bg-2 border border-line rounded-lg p-1 ${full ? "w-full" : ""}`}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" onClick={() => onChange(o.value)}
          className={`${full ? "flex-1 justify-center" : ""} inline-flex items-center gap-2 rounded-md font-semibold transition cursor-pointer
            ${size === "sm" ? "px-3 py-1.5 text-[13px]" : "px-3.5 py-2 text-[14px]"}
            ${o.value === value ? "bg-panel-2 text-text shadow-[0_2px_8px_rgba(0,0,0,0.35)]" : "text-muted hover:text-text hover:bg-white/[0.03]"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode }) {
  return (
    <label className="inline-flex items-center gap-3 cursor-pointer select-none">
      <input type="checkbox" className="hidden" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className={`relative w-10 h-[22px] rounded-full transition ${checked ? "bg-accent" : "bg-line-2"}`}>
        <span className={`absolute top-[3px] w-4 h-4 rounded-full bg-white transition ${checked ? "left-[21px]" : "left-[3px]"}`} />
      </span>
      <span className="text-[14px]">{label}</span>
    </label>
  );
}

export function Progress({ value }: { value: number | null }) {
  return (
    <div className={`h-1.5 bg-bg-2 border border-line rounded-full overflow-hidden ${value == null ? "indeterminate" : ""}`}>
      <i className="block h-full bg-gradient-to-r from-accent to-accent-2 transition-[width] duration-700" style={{ width: value == null ? "35%" : `${value}%` }} />
    </div>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => (
  <div className="text-dim text-center py-8 px-4 border border-dashed border-line rounded-xl">{children}</div>
);

export function Modal({ open, onClose, title, subtitle, actions, children, wide }:
  { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[3px] overflow-auto p-6 md:p-10" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`rise card mx-auto p-6 ${wide ? "max-w-[1180px]" : "max-w-[720px]"}`}>
        <div className="flex items-start justify-between gap-4 mb-3">
          <div className="min-w-0">
            <h3 className="text-[17px] font-bold m-0 leading-tight">{title}</h3>
            {subtitle && <div className="text-muted text-[12.5px] mt-1 truncate">{subtitle}</div>}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {actions}
            <button onClick={onClose} className="p-2 rounded-md hover:bg-white/5 text-muted cursor-pointer" aria-label="Close"><X size={18} /></button>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { value: T; label: ReactNode }[] }) {
  return (
    <div className="flex gap-1 border-b border-line mb-4">
      {tabs.map((t) => (
        <button key={t.value} onClick={() => onChange(t.value)}
          className={`px-3.5 py-2 -mb-px border-b-2 font-semibold text-[14px] cursor-pointer transition ${t.value === value ? "border-accent text-text" : "border-transparent text-muted hover:text-text"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <div className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-2 text-[14px]">
      {rows.map(([k, v]) => (<div key={k} className="contents"><div className="text-muted">{k}</div><div className="min-w-0">{v}</div></div>))}
    </div>
  );
}

export const Stat = ({ value, label }: { value: ReactNode; label: string }) => (
  <div className="flex flex-col"><b className="text-[24px] font-extrabold leading-none">{value}</b><span className="text-[11.5px] text-muted uppercase tracking-wider mt-1.5">{label}</span></div>
);
