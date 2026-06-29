"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { ArrowRight, BookOpen, Loader2, MessageSquareText, Send, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type Message = {
  role: "user" | "assistant";
  text: string;
  intent?: string;
  citations?: Array<{ paper_title?: string; paper_id?: string; section?: string; page?: number; passage?: string }>;
  sources?: Record<string, number>;
};

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", text: "Ask a question about your uploaded papers. I’ll answer from your corpus and keep the evidence attached." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const question = input.trim();
    if (!question || loading) return;
    setMessages((current) => [...current, { role: "user", text: question }]);
    setInput("");
    setLoading(true);
    try {
      const response = await fetch("/api/query?user_id=default_user", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "The query agent failed.");
      setMessages((current) => [...current, {
        role: "assistant",
        text: result.answer || "No sourced answer was found in this corpus.",
        intent: result.intent,
        citations: result.citations || [],
        sources: result.sources_used,
      }]);
    } catch (reason) {
      setMessages((current) => [...current, { role: "assistant", text: reason instanceof Error ? reason.message : "Unable to reach the query service." }]);
    } finally {
      setLoading(false);
    }
  }

  const latestSources = [...messages].reverse().find((message) => message.sources)?.sources;

  return (
    <div className="flex min-h-[calc(100vh-5rem)]">
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-slate-200 bg-white px-5 py-6 md:px-8">
          <Badge className="mb-3 bg-indigo-50 text-indigo-700">Corpus-grounded chat</Badge>
          <h1 className="text-2xl font-semibold tracking-tight">Ask PaperMind</h1>
          <p className="mt-1 text-sm text-slate-500">Readable answers, visible provenance, no black-on-black text.</p>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto bg-slate-50 p-5 pb-40 md:p-8 md:pb-40">
          {messages.map((message, index) => (
            <div key={index} className={`mx-auto max-w-3xl ${message.role === "user" ? "flex justify-end" : ""}`}>
              <div className={message.role === "user" ? "max-w-[82%] rounded-2xl rounded-br-md bg-slate-950 px-5 py-3 text-sm leading-6 text-white" : "w-full"}>
                {message.role === "assistant" && (
                  <div className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-500"><span className="grid h-7 w-7 place-items-center rounded-lg bg-indigo-50 text-indigo-700"><Sparkles size={14} /></span>PaperMind {message.intent && <Badge>{message.intent}</Badge>}</div>
                )}
                {message.role === "assistant" ? <Card className="p-5 text-sm leading-7 text-slate-800 shadow-none">{message.text}</Card> : message.text}
                {message.citations && message.citations.length > 0 && (
                  <div className="mt-3 grid gap-2">
                    {message.citations.map((citation, citationIndex) => (
                      <Link key={citationIndex} href={`/graph?focus=${encodeURIComponent(citation.paper_id || "")}`} className="rounded-xl border border-slate-200 bg-white p-4 text-left transition hover:border-indigo-200 hover:bg-indigo-50/40">
                        <div className="flex items-start justify-between gap-4"><div><p className="text-sm font-medium text-slate-900">[{citationIndex + 1}] {citation.paper_title || citation.paper_id}</p><p className="mt-1 text-xs text-slate-500">{citation.section || "Source"} · p. {citation.page ?? "—"}</p></div><ArrowRight size={15} className="text-slate-400" /></div>
                        {citation.passage && <p className="mt-3 border-l-2 border-indigo-200 pl-3 text-xs leading-5 text-slate-600">“{citation.passage}”</p>}
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && <div className="mx-auto flex max-w-3xl items-center gap-3 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" /> Searching graph paths and source passages…</div>}
        </div>

        <div className="fixed bottom-0 left-0 right-0 border-t border-slate-200 bg-white/95 p-4 backdrop-blur lg:left-64">
          <form onSubmit={submit} className="mx-auto flex max-w-3xl gap-3">
            <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="What are the main contributions across these papers?" className="h-12 min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-4 text-sm text-slate-950 outline-none placeholder:text-slate-400 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100" />
            <Button size="lg" disabled={loading || !input.trim()}><Send size={16} /><span className="hidden sm:inline">Ask</span></Button>
          </form>
        </div>
      </section>

      <aside className="hidden w-80 shrink-0 border-l border-slate-200 bg-white p-6 xl:block">
        <h2 className="flex items-center gap-2 font-medium"><BookOpen size={17} /> Retrieval provenance</h2>
        <p className="mt-2 text-xs leading-5 text-slate-500">PaperMind combines personal memory, graph traversal, and vector fallback.</p>
        <div className="mt-6 space-y-3">
          {[
            ["Personal corpus", latestSources?.personal_corpus || 0, "50%"],
            ["Graph traversal", latestSources?.graph_traversal || 0, "35%"],
            ["Vector fallback", latestSources?.vector || 0, "15%"],
          ].map(([label, count, weight]) => (
            <div key={String(label)} className="rounded-xl border border-slate-200 p-4"><div className="flex justify-between text-sm"><span>{label}</span><strong>{count}</strong></div><p className="mt-1 text-xs text-slate-400">Fusion weight {weight}</p></div>
          ))}
        </div>
        <div className="mt-6 rounded-xl bg-slate-950 p-4 text-white"><MessageSquareText size={18} /><p className="mt-3 text-sm font-medium">Click a citation</p><p className="mt-1 text-xs leading-5 text-slate-400">PaperMind opens the graph so you can inspect the supporting relationship.</p></div>
      </aside>
    </div>
  );
}
