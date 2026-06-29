"use client";

import { useEffect, useRef, useState } from "react";
import cytoscape, { Core, NodeSingular } from "cytoscape";
import { Expand, Info, Network, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type ElementData = { id?: string; source?: string; target?: string; label?: string; type?: string; [key: string]: unknown };
const colors: Record<string, string> = { Paper: "#7F77DD", Claim: "#1D9E75", Method: "#BA7517", Dataset: "#378ADD", Task: "#64748b", Gap: "#D85A30" };

export default function GraphPage() {
  const container = useRef<HTMLDivElement>(null);
  const graph = useRef<Core | null>(null);
  const [selected, setSelected] = useState<ElementData | null>(null);
  const [counts, setCounts] = useState({ nodes: 0, edges: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadGraph() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/graph?user_id=default_user", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to load graph.");
      setCounts({ nodes: data.nodes?.length || 0, edges: data.edges?.length || 0 });
      graph.current?.destroy();
      if (!container.current) return;
      graph.current = cytoscape({
        container: container.current,
        elements: [...(data.nodes || []), ...(data.edges || [])],
        layout: { name: "cose", animate: false, padding: 50 },
        style: [
          { selector: "node", style: { "background-color": (node: NodeSingular) => colors[String(node.data("type"))] || "#64748b", label: "data(label)", color: "#334155", "font-size": 10, "text-wrap": "wrap", "text-max-width": 110, "text-valign": "bottom", "text-margin-y": 9, width: 32, height: 32 } },
          { selector: "node[type = 'Paper']", style: { width: 48, height: 48, "font-weight": 600 } },
          { selector: "edge", style: { width: 1.5, "line-color": "#cbd5e1", "target-arrow-color": "#cbd5e1", "target-arrow-shape": "triangle", "curve-style": "bezier" } },
          { selector: "edge[type = 'CONTRADICTS']", style: { "line-color": "#E24B4A", "target-arrow-color": "#E24B4A", width: 3 } },
          { selector: "edge[type = 'SUPPORTS']", style: { "line-color": "#1D9E75", "target-arrow-color": "#1D9E75", width: 2.5 } },
          { selector: ":selected", style: { "border-width": 4, "border-color": "#0f172a" } },
        ] as any,
      });
      graph.current.on("tap", "node", (event) => setSelected(event.target.data()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load graph.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadGraph();
    return () => graph.current?.destroy();
  }, []);

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 p-5 md:p-8">
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div><Badge className="mb-3 bg-indigo-50 text-indigo-700">Interactive evidence map</Badge><h1 className="text-3xl font-semibold tracking-tight">Knowledge graph</h1><p className="mt-2 text-sm text-slate-600">Explore papers, claims, methods, datasets, and relationships created during ingestion.</p></div>
        <div className="flex gap-2"><Button variant="outline" onClick={() => graph.current?.fit(undefined, 40)}><Expand size={16} /> Fit graph</Button><Button onClick={loadGraph} disabled={loading}><RefreshCw className={loading ? "animate-spin" : ""} size={16} /> Refresh</Button></div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[1fr_320px]">
        <Card className="overflow-hidden shadow-none">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3 text-xs text-slate-500"><span>{counts.nodes} nodes · {counts.edges} edges</span><span>Click a node to inspect it</span></div>
          {error ? <div className="grid h-[620px] place-items-center p-8 text-sm text-rose-700">{error}</div> : <div ref={container} className="h-[620px] w-full bg-slate-50" />}
        </Card>
        <aside className="space-y-5">
          <Card className="shadow-none">
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Info size={17} /> Passage inspector</CardTitle></CardHeader>
            <CardContent>
              {selected ? <div className="space-y-4"><Badge style={{ backgroundColor: `${colors[String(selected.type)] || "#64748b"}18`, color: colors[String(selected.type)] || "#64748b" }}>{String(selected.type)}</Badge><h2 className="font-medium leading-6">{String(selected.label || selected.id)}</h2><div className="space-y-2 text-xs text-slate-500">{Object.entries(selected).filter(([key]) => !["id", "label", "type"].includes(key)).map(([key, value]) => <div key={key} className="flex justify-between gap-3 border-t border-slate-100 pt-2"><span>{key}</span><span className="text-right text-slate-700">{String(value)}</span></div>)}</div></div> : <p className="text-sm leading-6 text-slate-500">Select a graph node to see its source metadata and graph properties.</p>}
            </CardContent>
          </Card>
          <Card className="shadow-none"><CardHeader><CardTitle className="flex items-center gap-2 text-base"><Network size={17} /> Legend</CardTitle></CardHeader><CardContent className="grid grid-cols-2 gap-3">{Object.entries(colors).map(([type, color]) => <div key={type} className="flex items-center gap-2 text-xs text-slate-600"><span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />{type}</div>)}</CardContent></Card>
        </aside>
      </div>
    </div>
  );
}
