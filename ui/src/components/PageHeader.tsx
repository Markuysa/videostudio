import type { ReactNode } from "react";

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 flex-wrap mb-5">
      <div className="min-w-0">
        <h1 className="text-[28px] font-extrabold tracking-tight m-0 leading-tight">{title}</h1>
        {subtitle && <p className="text-muted mt-1.5 mb-0 max-w-[80ch]">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0 pt-1">{actions}</div>}
    </div>
  );
}
