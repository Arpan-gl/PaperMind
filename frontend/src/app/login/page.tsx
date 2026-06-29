"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { ArrowLeft, ArrowRight, LockKeyhole, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    const response = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await response.json();
    if (!response.ok) {
      setError(data.error || "Unable to continue.");
      setLoading(false);
      return;
    }
    const nextPath = new URLSearchParams(window.location.search).get("next");
    router.push(nextPath || "/dashboard");
    router.refresh();
  }

  return (
    <main className="grid min-h-screen bg-slate-50 lg:grid-cols-2">
      <section className="hidden bg-slate-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <Link href="/" className="flex items-center gap-2 text-lg font-semibold">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-white text-slate-950"><Sparkles size={18} /></span>
          PaperMind
        </Link>
        <div className="max-w-lg">
          <p className="text-sm font-medium text-indigo-300">Your literature, connected</p>
          <h1 className="mt-4 text-5xl font-semibold tracking-[-0.04em]">Return to the questions your papers are helping you answer.</h1>
          <p className="mt-6 leading-7 text-slate-400">Your original PDFs stay stored. Your graph keeps its IDs. Your answers remain traceable to evidence.</p>
        </div>
        <p className="text-xs text-slate-500">PaperMind research workspace</p>
      </section>

      <section className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <Button variant="ghost" asChild className="mb-5 -ml-3"><Link href="/"><ArrowLeft size={16} /> Back home</Link></Button>
          <Card>
            <CardHeader>
              <div className="mb-4 grid h-11 w-11 place-items-center rounded-xl bg-indigo-50 text-indigo-700"><LockKeyhole size={20} /></div>
              <CardTitle className="text-2xl">Log in to your workspace</CardTitle>
              <CardDescription>Use your email to open the PaperMind dashboard.</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={submit} className="space-y-4">
                <div>
                  <label htmlFor="email" className="mb-2 block text-sm font-medium text-slate-700">Email address</label>
                  <Input id="email" type="email" placeholder="researcher@example.com" value={email} onChange={(event) => setEmail(event.target.value)} required />
                </div>
                {error && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
                <Button className="w-full" size="lg" disabled={loading}>
                  {loading ? "Opening workspace…" : "Continue to dashboard"} <ArrowRight size={16} />
                </Button>
                <p className="text-center text-xs leading-5 text-slate-500">This local research build creates a secure browser session and does not use localStorage.</p>
              </form>
            </CardContent>
          </Card>
        </div>
      </section>
    </main>
  );
}
