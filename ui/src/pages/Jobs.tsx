import { Empty } from "../components/ui";
import { JobCard } from "../components/JobCard";
import { useStore } from "../store";

export function Jobs() {
  const { state } = useStore();
  const jobs = state!.jobs;
  return (
    <>
      <h1 className="text-[28px] font-extrabold tracking-tight m-0">Jobs</h1>
      <p className="text-muted mt-1 mb-6">Planning, rendering and re-assembly run as separate processes. Closing this page or the server does not stop them.</p>
      {jobs.length ? <div className="grid grid-cols-2 gap-3.5 max-md:grid-cols-1">{jobs.map((j) => <JobCard key={j.id} job={j} />)}</div> : <Empty>No jobs yet</Empty>}
    </>
  );
}
