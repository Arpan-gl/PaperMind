"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import cytoscape, { Core, NodeSingular, EdgeSingular } from "cytoscape";
import { Expand, RefreshCw, Network, ZoomIn, ZoomOut, Info, Filter, Layers } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// ── Palette ────────────────────────────────────────────────────────────────────
const NODE_CONFIG: Record<string, { color: string; border: string; size: number; shape: string }> = {
  Paper:         { color: "#6366f1", border: "#4f46e5", size: 52, shape: "ellipse" },
  Claim:         { color: "#10b981", border: "#059669", size: 36, shape: "round-rectangle" },
  Method:        { color: "#f59e0b", border: "#d97706", size: 40, shape: "diamond" },
  Dataset:       { color: "#3b82f6", border: "#2563eb", size: 36, shape: "hexagon" },
  Task:          { color: "#8b5cf6", border: "#7c3aed", size: 34, shape: "pentagon" },
  CitationStub:  { color: "#94a3b8", border: "#64748b", size: 28, shape: "ellipse" },
  Gap:           { color: "#ef4444", border: "#dc2626", size: 38, shape: "star" },
};

const EDGE_CONFIG: Record<string, { color: string; width: number; style: string; label: string }> = {
  HAS_CLAIM:        { color: "#10b981", width: 1.5,  style: "solid",  label: "has claim" },
  PROPOSES:         { color: "#f59e0b", width: 1.5,  style: "solid",  label: "proposes" },
  CITES:            { color: "#6366f1", width: 1.5,  style: "dashed", label: "cites" },
  CONTRADICTS:      { color: "#ef4444", width: 2.5,  style: "solid",  label: "contradicts" },
  SUPPORTS:         { color: "#10b981", width: 2.5,  style: "solid",  label: "supports" },
  USES_SAME_METHOD: { color: "#f59e0b", width: 2,    style: "dashed", label: "same method" },
  AUTHORED_BY:      { color: "#94a3b8", width: 1,    style: "dotted", label: "author" },
  USES_DATASET:     { color: "#3b82f6", width: 1.5,  style: "solid",  label: "uses dataset" },
};

type NodeData = {
  id?: string;
  label?: string;
  type?: string;
  rgs_score?: number;
  is_gap?: boolean;
  paper_count?: number;
  pub_year?: number;
  venue?: string;
  parent?: string;
  [key: string]: unknown;
};

type GraphElement = { data: NodeData };

// ── Cytoscape stylesheet builder ───────────────────────────────────────────────
function buildStylesheet() {
  const styles: any[] = [
    // Base node
    {
      selector: "node",
      style: {
        "background-color": "#6366f1",
        "border-color": "#4f46e5",
        "border-width": 2,
        label: "data(label)",
        color: "#f8fafc",
        "font-size": 10,
        "font-weight": 500,
        "text-wrap": "wrap",
        "text-max-width": 120,
        "text-valign": "bottom",
        "text-margin-y": 6,
        "text-outline-color": "#0f172a",
        "text-outline-width": 2,
        width: 36,
        height: 36,
        "overlay-padding": 8,
        "transition-property": "border-width, border-color, background-color",
        "transition-duration": "0.15s",
      },
    },
    // Node-type overrides
    ...Object.entries(NODE_CONFIG).map(([type, cfg]) => ({
      selector: `node[type = '${type}']`,
      style: {
        "background-color": cfg.color,
        "border-color": cfg.border,
        shape: cfg.shape,
        width: cfg.size,
        height: cfg.size,
      },
    })),
    // Gap nodes — glowing red ring
    {
      selector: "node[?is_gap]",
      style: {
        "border-width": 3,
        "border-color": "#ef4444",
        "background-color": "#fca5a5",
      },
    },
    // Paper nodes — bold label
    {
      selector: "node[type = 'Paper']",
      style: { "font-size": 11, "font-weight": 700, color: "#fff" },
    },
    // Hover / selected
    {
      selector: "node:selected",
      style: {
        "border-width": 4,
        "border-color": "#f0abfc",
        "background-color": "#a855f7",
      },
    },
    {
      selector: "node.highlighted",
      style: { "border-width": 3, "border-color": "#fbbf24", opacity: 1 },
    },
    {
      selector: "node.dimmed",
      style: { opacity: 0.15 },
    },
    // Base edge
    {
      selector: "edge",
      style: {
        width: 1.5,
        "line-color": "#475569",
        "target-arrow-color": "#475569",
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "arrow-scale": 1.2,
        opacity: 0.7,
        label: "data(edgeLabel)",
        "font-size": 8,
        "font-weight": 400,
        color: "#94a3b8",
        "text-rotation": "autorotate",
        "text-outline-color": "#0f172a",
        "text-outline-width": 1.5,
        "text-margin-y": -6,
      },
    },
    // Edge-type overrides
    ...Object.entries(EDGE_CONFIG).map(([type, cfg]) => ({
      selector: `edge[type = '${type}']`,
      style: {
        "line-color": cfg.color,
        "target-arrow-color": cfg.color,
        width: cfg.width,
        "line-style": cfg.style as any,
      },
    })),
    // Selected edge
    {
      selector: "edge:selected",
      style: { "line-color": "#f0abfc", "target-arrow-color": "#f0abfc", width: 3, opacity: 1 },
    },
    {
      selector: "edge.dimmed",
      style: { opacity: 0.05 },
    },
  ];
  return styles;
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function GraphPage() {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [selected, setSelected] = useState<NodeData | null>(null);
  const [counts, setCounts] = useState({ nodes: 0, edges: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showClaims, setShowClaims] = useState(true);
  const [showCitations, setShowCitations] = useState(false);
  const [maxClaims, setMaxClaims] = useState(5);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError("");
    setSelected(null);
    try {
      const params = new URLSearchParams({
        user_id: "default_user",
        include_claims: String(showClaims),
        include_citations: String(showCitations),
        max_claims: String(maxClaims),
      });
      const res = await fetch(`/api/graph?${params}`, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Unable to load graph.");

      // Strip `parent` so Cytoscape does NOT create compound nodes
      const nodes: GraphElement[] = (data.nodes || []).map((n: GraphElement) => {
        const { parent: _p, ...rest } = n.data;
        return { data: { ...rest } };
      });
      // Annotate edges with display label
      const edges: GraphElement[] = (data.edges || []).map((e: GraphElement) => ({
        data: {
          ...e.data,
          edgeLabel: showEdgeLabels ? (EDGE_CONFIG[e.data.type as string]?.label ?? "") : "",
        },
      }));

      setCounts({ nodes: nodes.length, edges: edges.length });
      cy.current?.destroy();
      if (!container.current) return;

      cy.current = cytoscape({
        container: container.current,
        elements: [...nodes, ...edges],
        layout: {
          name: "cose",
          animate: true,
          animationDuration: 600,
          padding: 60,
          nodeRepulsion: () => 8000,
          idealEdgeLength: () => 120,
          edgeElasticity: () => 100,
          gravity: 0.25,
          randomize: false,
          fit: true,
        } as any,
        style: buildStylesheet(),
        minZoom: 0.1,
        maxZoom: 4,
        wheelSensitivity: 0.3,
      });

      // Tap node: highlight neighbourhood
      cy.current.on("tap", "node", (evt) => {
        const node = evt.target;
        const data = node.data() as NodeData;
        setSelected(data);

        // Dim all, then highlight the node + its neighbourhood
        cy.current?.elements().addClass("dimmed").removeClass("highlighted");
        const neighbourhood = node.closedNeighborhood();
        neighbourhood.removeClass("dimmed").addClass("highlighted");
        node.removeClass("dimmed");
      });

      // Tap background: clear selection
      cy.current.on("tap", (evt) => {
        if (evt.target === cy.current) {
          setSelected(null);
          cy.current?.elements().removeClass("dimmed highlighted");
        }
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load graph.");
    } finally {
      setLoading(false);
    }
  }, [showClaims, showCitations, maxClaims, showEdgeLabels]);

  useEffect(() => {
    loadGraph();
    return () => cy.current?.destroy();
  }, []);

  // Legend entries (only types present in the graph)
  const legendEntries = Object.entries(NODE_CONFIG);

  return (
    <div className="mx-auto max-w-[1600px] space-y-5 p-5 md:p-8">
      {/* Header */}
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <Badge className="mb-3 bg-indigo-50 text-indigo-700 border border-indigo-200">
            GraphRAG Knowledge Graph
          </Badge>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Research Graph</h1>
          <p className="mt-1.5 text-sm text-slate-500">
            Papers · Claims · Methods · Relationships — powered by GraphRAG retrieval
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => cy.current?.fit(undefined, 50)}>
            <Expand size={14} className="mr-1" /> Fit
          </Button>
          <Button variant="outline" size="sm" onClick={() => cy.current?.zoom(cy.current.zoom() * 1.25)}>
            <ZoomIn size={14} />
          </Button>
          <Button variant="outline" size="sm" onClick={() => cy.current?.zoom(cy.current.zoom() * 0.8)}>
            <ZoomOut size={14} />
          </Button>
          <Button size="sm" onClick={loadGraph} disabled={loading}>
            <RefreshCw className={loading ? "animate-spin mr-1" : "mr-1"} size={14} />
            {loading ? "Loading…" : "Refresh"}
          </Button>
        </div>
      </section>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <Filter size={14} className="text-slate-400" />
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Filters</span>
        <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showClaims}
            onChange={(e) => setShowClaims(e.target.checked)}
            className="accent-indigo-600"
          />
          Claims
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showCitations}
            onChange={(e) => setShowCitations(e.target.checked)}
            className="accent-indigo-600"
          />
          Citation stubs
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showEdgeLabels}
            onChange={(e) => setShowEdgeLabels(e.target.checked)}
            className="accent-indigo-600"
          />
          Edge labels
        </label>
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span>Claims per paper:</span>
          <input
            type="range"
            min={1}
            max={20}
            value={maxClaims}
            onChange={(e) => setMaxClaims(Number(e.target.value))}
            className="w-24 accent-indigo-600"
          />
          <span className="w-4 text-center font-medium text-indigo-600">{maxClaims}</span>
        </div>
        <Button size="sm" variant="outline" className="ml-auto text-xs h-7 px-3" onClick={loadGraph} disabled={loading}>
          Apply
        </Button>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1fr_300px]">
        {/* Graph canvas */}
        <Card className="overflow-hidden shadow-sm border-slate-200">
          <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-5 py-2.5 text-xs text-slate-500">
            <span className="font-medium">
              <span className="text-indigo-600 font-semibold">{counts.nodes}</span> nodes ·{" "}
              <span className="text-indigo-600 font-semibold">{counts.edges}</span> edges
            </span>
            <span className="text-slate-400">Click a node to inspect · Scroll to zoom</span>
          </div>
          {/* Canvas is ALWAYS mounted — Cytoscape owns the DOM inside it.
              Loading and error states are absolute overlays so React never
              unmounts the ref div (which causes removeChild crashes). */}
          <div className="relative">
            <div
              ref={container}
              className="h-[640px] w-full"
              style={{
                background: "linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%)",
              }}
            />
            {loading && (
              <div className="absolute inset-0 grid place-items-center bg-slate-900/95">
                <div className="flex flex-col items-center gap-4">
                  <div className="relative w-16 h-16">
                    <div className="absolute inset-0 rounded-full border-4 border-indigo-500/30 animate-ping" />
                    <div className="absolute inset-2 rounded-full border-4 border-indigo-500 border-t-transparent animate-spin" />
                  </div>
                  <p className="text-sm text-slate-400 font-medium">Building knowledge graph…</p>
                </div>
              </div>
            )}
            {error && (
              <div className="absolute inset-0 grid place-items-center bg-rose-950/90">
                <div className="text-center px-8">
                  <div className="text-3xl mb-3">⚠️</div>
                  <p className="text-sm text-rose-300">{error}</p>
                </div>
              </div>
            )}
          </div>
        </Card>

        {/* Sidebar */}
        <aside className="space-y-4">
          {/* Node inspector */}
          <Card className="shadow-sm border-slate-200">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold">
                <Info size={15} className="text-indigo-500" /> Node Inspector
              </CardTitle>
            </CardHeader>
            <CardContent>
              {selected ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <span
                      className="h-3 w-3 rounded-full flex-shrink-0"
                      style={{ backgroundColor: NODE_CONFIG[selected.type as string]?.color ?? "#64748b" }}
                    />
                    <Badge
                      className="text-xs"
                      style={{
                        backgroundColor: `${NODE_CONFIG[selected.type as string]?.color ?? "#64748b"}22`,
                        color: NODE_CONFIG[selected.type as string]?.color ?? "#64748b",
                        border: `1px solid ${NODE_CONFIG[selected.type as string]?.color ?? "#64748b"}44`,
                      }}
                    >
                      {selected.type}
                    </Badge>
                    {selected.is_gap && (
                      <Badge className="text-xs bg-red-50 text-red-600 border border-red-200">GAP</Badge>
                    )}
                  </div>
                  <h2 className="text-sm font-semibold leading-5 text-slate-800 line-clamp-4">
                    {String(selected.label || selected.id)}
                  </h2>
                  <div className="space-y-1.5">
                    {Object.entries(selected)
                      .filter(([k, v]) => !["id", "label", "type"].includes(k) && v !== undefined && v !== null && v !== "")
                      .map(([key, value]) => (
                        <div key={key} className="flex justify-between gap-3 border-t border-slate-100 pt-1.5 text-xs">
                          <span className="text-slate-400 capitalize">{key.replace(/_/g, " ")}</span>
                          <span className="text-right text-slate-700 font-medium max-w-[140px] break-words">
                            {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              ) : (
                <p className="text-xs leading-5 text-slate-400">
                  Click any node in the graph to inspect its metadata, RGS score, and relationships.
                </p>
              )}
            </CardContent>
          </Card>

          {/* Legend */}
          <Card className="shadow-sm border-slate-200">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold">
                <Layers size={15} className="text-indigo-500" /> Legend
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Node Types</p>
                <div className="grid grid-cols-2 gap-y-2 gap-x-3">
                  {legendEntries.map(([type, cfg]) => (
                    <div key={type} className="flex items-center gap-2 text-xs text-slate-600">
                      <span
                        className="h-2.5 w-2.5 flex-shrink-0 rounded-sm"
                        style={{ backgroundColor: cfg.color }}
                      />
                      {type}
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Edge Types</p>
                <div className="space-y-1.5">
                  {Object.entries(EDGE_CONFIG).map(([type, cfg]) => (
                    <div key={type} className="flex items-center gap-2 text-xs text-slate-600">
                      <div className="h-0.5 w-6 flex-shrink-0" style={{ backgroundColor: cfg.color }} />
                      {cfg.label}
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
