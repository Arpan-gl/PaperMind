"use client";

import { useState } from "react";
import { AlertTriangle, Beaker, Lightbulb, Loader2, Radar } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Gap = {
  gap_id?: string;
  claim_id?: string;
  gap_type?: string;
  claim_text?: string;
  rgs_score?: number;
  referenced_by_count?: number;
  suggested_investigation?: string;
  human_description?: string;
};

export default function GapsPage() {
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function scan() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/graph/gaps?user_id=default_user", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Gap detection failed.");
      setGaps(data.gaps || []);
      setSummary(data.summary || {});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Gap detection failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-5 md:p-8">
      <section className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
        <div><Badge className="mb-3 bg-indigo-50 text-indigo-700">Research gap score</Badge><h1 className="text-3xl font-semibold tracking-tight">Find the questions your corpus leaves open</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">Rank under-supported claims, isolated methods, and methodological weaknesses by graph structure—not by a generic keyword search.</p></div>
        <Button onClick={scan} disabled={loading}>{loading ? <Loader2 size={16} className="animate-spin" /> : <Radar size={16} />}{loading ? "Scanning corpus…" : "Find gaps"}</Button>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        {[
          { label: "Critical", value: summary.critical_gaps || 0, icon: AlertTriangle, classes: "bg-rose-50 text-rose-700" },
          { label: "Moderate", value: summary.moderate_gaps || 0, icon: Lightbulb, classes: "bg-amber-50 text-amber-700" },
          { label: "Orphan methods", value: summary.orphan_methods || 0, icon: Beaker, classes: "bg-blue-50 text-blue-700" },
        ].map(({ label, value, icon: ItemIcon, classes }) => {
          return <Card key={label} className="shadow-none"><CardContent className="flex items-center justify-between p-5"><div><p className="text-sm text-slate-500">{label}</p><p className="mt-1 text-3xl font-semibold">{value}</p></div><span className={`grid h-11 w-11 place-items-center rounded-xl ${classes}`}><ItemIcon size={19} /></span></CardContent></Card>;
        })}
      </section>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div>}

      <section className="space-y-4">
        {!loading && gaps.length === 0 ? (
          <Card className="border-dashed py-12 text-center shadow-none"><CardContent><Radar className="mx-auto text-slate-300" size={30} /><h2 className="mt-4 font-medium">No gap report yet</h2><p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">Upload a few related papers, then run Find gaps. Stronger corpora produce more meaningful topology signals.</p></CardContent></Card>
        ) : gaps.map((gap, index) => {
          const type = gap.gap_type || "moderate_gap";
          const variant = type.includes("critical") ? "danger" : type.includes("orphan") ? "secondary" : "warning";
          return (
            <Card key={gap.gap_id || gap.claim_id || index} className="shadow-none">
              <CardHeader className="flex-row items-start justify-between gap-5">
                <div><Badge variant={variant}>{type.replaceAll("_", " ")}</Badge><CardTitle className="mt-4 max-w-3xl text-base leading-6">{gap.claim_text || "Unresolved corpus relationship"}</CardTitle><CardDescription className="mt-2">{gap.human_description || `${gap.referenced_by_count || 0} papers reference this area, but direct support remains limited.`}</CardDescription></div>
                <div className="shrink-0 rounded-xl bg-slate-950 px-4 py-3 text-center text-white"><p className="text-[10px] uppercase tracking-wider text-slate-400">RGS</p><p className="text-xl font-semibold">{(gap.rgs_score || 0).toFixed(3)}</p></div>
              </CardHeader>
              <CardContent><div className="rounded-xl bg-indigo-50 p-4 text-sm leading-6 text-indigo-900"><strong>Suggested investigation:</strong> {gap.suggested_investigation || "Compare the claim across additional independent datasets and evaluation settings."}</div></CardContent>
            </Card>
          );
        })}
      </section>
    </div>
  );
}
