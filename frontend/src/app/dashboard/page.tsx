"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, FileText, MessageSquareText, Network, Plus, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type GraphNode = { data: { type: string; is_gap?: boolean } };

export default function DashboardPage() {
  const [stats, setStats] = useState({ papers: 0, claims: 0, methods: 0, gaps: 0 });
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch("/api/papers?user_id=default_user").then((response) => response.json()),
      fetch("/api/graph?user_id=default_user").then((response) => response.json()),
    ])
      .then(([papers, graph]) => {
        const nodes: GraphNode[] = graph.nodes || [];
        setStats({
          papers: papers.length || 0,
          claims: nodes.filter((node) => node.data.type === "Claim").length,
          methods: nodes.filter((node) => node.data.type === "Method").length,
          gaps: nodes.filter((node) => node.data.is_gap).length,
        });
      })
      .catch(() => setOffline(true));
  }, []);

  return (
    <div className="mx-auto max-w-7xl space-y-8 p-5 md:p-8">
      <section className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
        <div>
          <Badge className="mb-3 bg-indigo-50 text-indigo-700">Living graph workspace</Badge>
          <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">Good to see you. What are we reading?</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">Upload papers, inspect graph changes, ask grounded questions, and prioritize research gaps from one focused workspace.</p>
        </div>
        <Button asChild><Link href="/upload"><Plus size={16} /> Upload a paper</Link></Button>
      </section>

      {offline && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">The backend is offline. Start FastAPI on port 8000 to load live corpus metrics.</div>}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Papers", value: stats.papers, description: "Stored source PDFs", icon: FileText, classes: "bg-indigo-50 text-indigo-700" },
          { label: "Claims", value: stats.claims, description: "Traceable assertions", icon: Sparkles, classes: "bg-emerald-50 text-emerald-700" },
          { label: "Methods", value: stats.methods, description: "Connected techniques", icon: Network, classes: "bg-amber-50 text-amber-700" },
          { label: "Open gaps", value: stats.gaps, description: "RGS-prioritized", icon: AlertTriangle, classes: "bg-rose-50 text-rose-700" },
        ].map(({ label, value, description, icon: ItemIcon, classes }) => {
          return (
            <Card key={String(label)} className="shadow-none">
              <CardContent className="flex items-center justify-between p-5">
                <div><p className="text-sm text-slate-500">{label}</p><p className="mt-1 text-3xl font-semibold">{value}</p><p className="mt-1 text-xs text-slate-400">{description}</p></div>
                <span className={`grid h-11 w-11 place-items-center rounded-xl ${classes}`}><ItemIcon size={19} /></span>
              </CardContent>
            </Card>
          );
        })}
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.4fr_.6fr]">
        <Card className="shadow-none">
          <CardHeader><CardTitle>Continue your research</CardTitle><CardDescription>Each tool has its own focused space—no more everything-on-one-page clutter.</CardDescription></CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            {[
              { href: "/upload", title: "Add source material", text: "Store a PDF and follow every processing stage.", icon: FileText },
              { href: "/graph", title: "Explore connections", text: "Inspect papers, methods, claims, and evidence.", icon: Network },
              { href: "/chat", title: "Ask the corpus", text: "Get readable answers with linked citations.", icon: MessageSquareText },
              { href: "/gaps", title: "Find research gaps", text: "Rank under-supported claims with RGS.", icon: AlertTriangle },
            ].map(({ href, title, text, icon: ItemIcon }) => {
              return (
                <Link key={href} href={href} className="group rounded-xl border border-slate-200 p-5 transition hover:border-slate-300 hover:bg-slate-50">
                  <ItemIcon size={19} className="text-slate-500" /><h3 className="mt-4 font-medium">{title}</h3><p className="mt-1 text-sm leading-6 text-slate-500">{text}</p>
                  <span className="mt-4 flex items-center gap-1 text-sm font-medium">Open <ArrowRight size={14} className="transition group-hover:translate-x-1" /></span>
                </Link>
              );
            })}
          </CardContent>
        </Card>
        <Card className="border-slate-900 bg-slate-950 text-white shadow-none">
          <CardHeader><CardTitle className="text-white">A reliable corpus starts with the source.</CardTitle><CardDescription className="text-slate-400">Uploads are now retained in a user-scoped folder, and processing errors are reported instead of silently swallowed.</CardDescription></CardHeader>
          <CardContent><Button variant="outline" className="border-white/20 bg-white/10 text-white hover:bg-white/15 hover:text-white" asChild><Link href="/upload">Review upload pipeline <ArrowRight size={15} /></Link></Button></CardContent>
        </Card>
      </section>
    </div>
  );
}
