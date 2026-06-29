import Link from "next/link";
import { ArrowRight, BrainCircuit, Check, FileSearch, Network, Quote, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

const capabilities = [
  { icon: FileSearch, title: "Structured paper understanding", text: "Extract methods, claims, datasets, citations, and evidence—not just disconnected chunks." },
  { icon: Network, title: "A graph that evolves", text: "Each new paper enriches your existing corpus with support, contradiction, and shared-method links." },
  { icon: BrainCircuit, title: "Answers grounded in your work", text: "Ask across your own library and trace every answer back to a paper, section, and passage." },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white text-slate-950">
      <header className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2 text-lg font-semibold">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-slate-950 text-white"><Sparkles size={18} /></span>
          PaperMind
        </Link>
        <nav className="hidden items-center gap-8 text-sm text-slate-600 md:flex">
          <a href="#why" className="hover:text-slate-950">Why PaperMind</a>
          <a href="#workflow" className="hover:text-slate-950">How it works</a>
          <a href="#trust" className="hover:text-slate-950">Your data</a>
        </nav>
        <div className="flex items-center gap-2">
          <Button variant="ghost" asChild><Link href="/login">Log in</Link></Button>
          <Button asChild><Link href="/login">Get started <ArrowRight size={15} /></Link></Button>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden border-y border-slate-100 bg-slate-50">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_72%_30%,rgba(99,102,241,0.14),transparent_34%)]" />
          <div className="relative mx-auto grid max-w-7xl gap-14 px-6 py-24 lg:grid-cols-[1.05fr_.95fr] lg:py-32">
            <div className="max-w-2xl">
              <Badge className="mb-6 border border-indigo-100 bg-indigo-50 text-indigo-700">Living research intelligence</Badge>
              <h1 className="text-5xl font-semibold tracking-[-0.045em] text-slate-950 sm:text-6xl lg:text-7xl">
                Your papers should become more useful with every upload.
              </h1>
              <p className="mt-7 max-w-xl text-lg leading-8 text-slate-600">
                PaperMind turns a personal PDF library into a durable knowledge graph—connecting claims, methods, citations, contradictions, and open research questions.
              </p>
              <div className="mt-9 flex flex-wrap gap-3">
                <Button size="lg" asChild><Link href="/login">Build your research graph <ArrowRight size={17} /></Link></Button>
                <Button size="lg" variant="outline" asChild><a href="#workflow">See how it works</a></Button>
              </div>
              <div className="mt-8 flex flex-wrap gap-5 text-sm text-slate-500">
                {["Source-linked answers", "Persistent PDF storage", "Personal corpus only"].map((item) => (
                  <span key={item} className="flex items-center gap-2"><Check size={15} className="text-emerald-600" />{item}</span>
                ))}
              </div>
            </div>

            <div className="relative hidden min-h-[470px] lg:block">
              <div className="absolute inset-6 rounded-[2rem] border border-slate-200 bg-white p-6 shadow-2xl shadow-slate-200/70">
                <div className="flex items-center justify-between border-b border-slate-100 pb-5">
                  <div><p className="font-medium">Knowledge graph</p><p className="text-xs text-slate-500">5 papers · 42 entities · 68 relations</p></div>
                  <Badge variant="success">Synced</Badge>
                </div>
                <div className="relative mt-5 h-[315px] overflow-hidden rounded-2xl bg-slate-950">
                  <div className="absolute left-16 top-24 h-px w-52 rotate-12 bg-indigo-400/60" />
                  <div className="absolute right-16 top-32 h-px w-48 -rotate-[28deg] bg-emerald-400/60" />
                  <div className="absolute left-36 bottom-20 h-px w-44 rotate-[32deg] bg-amber-400/60" />
                  {[
                    ["Paper", "left-10 top-12 bg-indigo-500"], ["Method", "right-10 top-16 bg-amber-500"],
                    ["Claim", "left-1/2 top-1/2 bg-emerald-500"], ["Dataset", "left-20 bottom-10 bg-blue-500"],
                    ["Gap", "right-16 bottom-10 bg-rose-500"],
                  ].map(([label, classes]) => (
                    <span key={label} className={`absolute grid h-20 w-20 place-items-center rounded-full border-4 border-white/10 text-xs font-medium text-white shadow-lg ${classes}`}>{label}</span>
                  ))}
                </div>
                <div className="mt-5 flex items-center gap-3 rounded-xl bg-slate-50 p-3 text-sm text-slate-600">
                  <Quote size={16} className="text-indigo-600" /> Every answer opens back to the exact supporting passage.
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="why" className="mx-auto max-w-7xl px-6 py-24">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold text-indigo-600">Beyond flat PDF search</p>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight">A research workspace that understands relationships.</h2>
            <p className="mt-4 text-slate-600">Ordinary chat-with-PDF tools forget how papers relate. PaperMind keeps those relationships visible and queryable.</p>
          </div>
          <div className="mt-12 grid gap-5 md:grid-cols-3">
            {capabilities.map((item) => (
              <Card key={item.title} className="shadow-none">
                <CardContent className="p-7">
                  <span className="grid h-11 w-11 place-items-center rounded-xl bg-slate-100"><item.icon size={20} /></span>
                  <h3 className="mt-6 text-lg font-semibold">{item.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{item.text}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <section id="workflow" className="border-y border-slate-200 bg-slate-950 text-white">
          <div className="mx-auto max-w-7xl px-6 py-24">
            <div className="grid gap-12 lg:grid-cols-2">
              <div><p className="text-sm font-semibold text-indigo-300">From PDF to connected evidence</p><h2 className="mt-3 text-4xl font-semibold tracking-tight">Upload once. Keep the source. Build on it continuously.</h2></div>
              <div className="space-y-7">
                {[
                  ["01", "Store", "The original PDF is retained in your user-scoped upload folder."],
                  ["02", "Understand", "Agents extract the five-module research schema and preserve source context."],
                  ["03", "Connect", "Kuzu and Cognee update the graph and memory layer for future queries."],
                ].map(([number, title, text]) => (
                  <div key={number} className="grid grid-cols-[3rem_1fr] gap-4 border-b border-white/10 pb-7">
                    <span className="text-sm text-indigo-300">{number}</span><div><h3 className="font-medium">{title}</h3><p className="mt-1 text-sm leading-6 text-slate-400">{text}</p></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="trust" className="mx-auto max-w-4xl px-6 py-24 text-center">
          <h2 className="text-4xl font-semibold tracking-tight">Ready to make your literature review feel less like archaeology?</h2>
          <p className="mx-auto mt-4 max-w-2xl text-slate-600">Start a private workspace, upload a paper, and watch the graph become more useful instead of more cluttered.</p>
          <Button size="lg" className="mt-8" asChild><Link href="/login">Get started with PaperMind <ArrowRight size={17} /></Link></Button>
        </section>
      </main>
      <footer className="border-t border-slate-200 px-6 py-8 text-center text-sm text-slate-500">PaperMind · Durable research memory, grounded in your sources.</footer>
    </div>
  );
}
