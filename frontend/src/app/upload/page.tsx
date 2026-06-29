"use client";

import { DragEvent, useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Check, FileText, FolderCheck, Loader2, UploadCloud } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Job = {
  task_id: string;
  status: "queued" | "analyzing" | "graph_building" | "complete" | "failed";
  original_filename: string;
  stored_path?: string;
  paper_title?: string;
  error?: string;
  cognee_stored?: boolean;
  cognee_status?: "syncing" | "ready" | "failed";
  stage?: string;
  progress?: number;
  processing_seconds?: number;
  extraction_mode?: "ai" | "local_fast";
  retry_count?: number;
  delta?: Record<string, number>;
};

const steps = [
  ["queued", "PDF stored"],
  ["analyzing", "Extracting evidence"],
  ["graph_building", "Updating knowledge graph"],
  ["complete", "Ready to explore"],
];

export default function UploadPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);

  const poll = useCallback(async (taskId: string) => {
    const response = await fetch(`/api/papers/jobs/${taskId}?user_id=default_user`, { cache: "no-store" });
    if (!response.ok) return;
    const next = await response.json();
    setJob(next);
    if (next.status !== "complete" && next.status !== "failed") {
      window.setTimeout(() => poll(taskId), 1800);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/papers/latest-job?user_id=default_user", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return;
        const latest: Job = await response.json();
        if (cancelled) return;
        setJob(latest);
        if (latest.status !== "complete" && latest.status !== "failed") {
          poll(latest.task_id);
        }
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [poll]);

  useEffect(() => {
    if (!job || job.status === "complete" || job.status === "failed") return;
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [job?.status]);

  async function upload(file?: File) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Choose a PDF file.");
      return;
    }
    setError("");
    setElapsed(0);
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch("/api/papers/ingest?user_id=default_user", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Upload failed.");
      const initial: Job = { task_id: data.task_id, status: "queued", original_filename: file.name };
      setJob(initial);
      poll(data.task_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function retry() {
    if (!job) return;
    setError("");
    setElapsed(0);
    try {
      const response = await fetch(
        `/api/papers/jobs/${job.task_id}/retry?user_id=default_user`,
        { method: "POST" },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Retry failed.");
      setJob((current) => current ? { ...current, status: "queued", stage: "Restarting worker", progress: 5, error: undefined } : current);
      poll(job.task_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Retry failed.");
    }
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    upload(event.dataTransfer.files[0]);
  }

  const activeIndex = job ? steps.findIndex(([status]) => status === job.status) : -1;

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-5 md:p-8">
      <section>
        <Badge className="mb-3 bg-indigo-50 text-indigo-700">Ingestion pipeline</Badge>
        <h1 className="text-3xl font-semibold tracking-tight">Add papers to your research graph</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">The original PDF is stored first. PaperMind then extracts its research structure, updates Cognee, and commits graph nodes and edges.</p>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.2fr_.8fr]">
        <Card className="shadow-none">
          <CardHeader><CardTitle>Upload a PDF</CardTitle><CardDescription>One paper at a time gives you a clear, inspectable processing trail.</CardDescription></CardHeader>
          <CardContent>
            <div
              onDragEnter={() => setDragging(true)}
              onDragLeave={() => setDragging(false)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={drop}
              className={`grid min-h-72 place-items-center rounded-xl border-2 border-dashed p-8 text-center transition ${dragging ? "border-indigo-400 bg-indigo-50" : "border-slate-200 bg-slate-50"}`}
            >
              <div>
                <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-white text-indigo-700 shadow-sm"><UploadCloud size={25} /></span>
                <h2 className="mt-5 font-medium">Drop a research PDF here</h2>
                <p className="mt-2 text-sm text-slate-500">Up to 50 MB. The file remains stored after processing.</p>
                <input ref={inputRef} type="file" accept=".pdf,application/pdf" className="hidden" onChange={(event) => upload(event.target.files?.[0])} />
                <Button className="mt-5" onClick={() => inputRef.current?.click()} disabled={uploading}>
                  {uploading ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
                  {uploading ? "Storing PDF…" : "Choose PDF"}
                </Button>
              </div>
            </div>
            {error && <div className="mt-4 flex items-start gap-2 rounded-lg bg-rose-50 p-3 text-sm text-rose-700"><AlertCircle size={17} className="mt-0.5 shrink-0" />{error}</div>}
          </CardContent>
        </Card>

        <Card className="shadow-none">
          <CardHeader><CardTitle>Processing status</CardTitle><CardDescription>{job ? job.original_filename : "Your latest upload will appear here."}</CardDescription></CardHeader>
          <CardContent>
            {job && (
              <div className="mb-5 rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="font-medium text-slate-700">{job.stage || "Waiting for worker"}</span>
                  <span className="tabular-nums text-slate-500">{Math.round(job.processing_seconds ?? elapsed)}s</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
                  <div className="h-full rounded-full bg-indigo-600 transition-all duration-500" style={{ width: `${job.progress ?? 5}%` }} />
                </div>
                {job.status === "queued" && elapsed > 8 && (
                  <div className="mt-3 flex items-center justify-between gap-3 text-xs text-amber-700">
                    <span>The worker has not started yet. Restart it using the stored PDF.</span>
                    <Button size="sm" variant="outline" onClick={retry}>Restart</Button>
                  </div>
                )}
              </div>
            )}
            <div className="space-y-1">
              {steps.map(([status, label], index) => {
                const done = job?.status === "complete" || index < activeIndex;
                const active = index === activeIndex && job?.status !== "failed";
                return (
                  <div key={status} className="flex gap-3">
                    <div className="flex flex-col items-center">
                      <span className={`grid h-8 w-8 place-items-center rounded-full border text-xs ${done ? "border-emerald-600 bg-emerald-600 text-white" : active ? "border-indigo-600 bg-indigo-50 text-indigo-700" : "border-slate-200 text-slate-400"}`}>
                        {done ? <Check size={15} /> : active ? <Loader2 size={14} className="animate-spin" /> : index + 1}
                      </span>
                      {index < steps.length - 1 && <span className="h-9 w-px bg-slate-200" />}
                    </div>
                    <div className="pt-1"><p className={`text-sm font-medium ${active || done ? "text-slate-950" : "text-slate-400"}`}>{label}</p><p className="text-xs text-slate-400">{status === "queued" ? "A durable copy is written before analysis." : status === "graph_building" ? "Committing the usable Kuzu graph." : ""}</p></div>
                  </div>
                );
              })}
            </div>

            {job?.status === "failed" && (
              <div className="mt-5 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">
                <p><strong>Processing failed:</strong> {job.error || "Unknown worker error."} Your PDF is still stored.</p>
                <Button size="sm" variant="outline" className="mt-3" onClick={retry}>Retry stored PDF</Button>
              </div>
            )}
            {job?.status === "complete" && (
              <div className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                <div className="flex items-center gap-2 font-medium text-emerald-800"><FolderCheck size={18} /> {job.paper_title || "Paper ready"}</div>
                <p className="mt-2 text-xs leading-5 text-emerald-700">{job.delta?.nodes_created || 0} nodes created · {job.delta?.cross_paper_edges || 0} cross-paper edges · Cognee {job.cognee_stored ? "updated" : "needs attention"}</p>
                {job.cognee_status === "syncing" && <p className="mt-1 text-xs text-emerald-700">Your graph is ready now; Cognee continues syncing in the background.</p>}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
