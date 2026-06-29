"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, Bell, FileUp, LayoutDashboard, LogOut, MessageSquareText, Network, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const publicRoutes = new Set(["/", "/login"]);
const navItems = [
  { name: "Overview", path: "/dashboard", icon: LayoutDashboard },
  { name: "Upload papers", path: "/upload", icon: FileUp },
  { name: "Knowledge graph", path: "/graph", icon: Network },
  { name: "Ask PaperMind", path: "/chat", icon: MessageSquareText },
  { name: "Research gaps", path: "/gaps", icon: AlertTriangle },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [connected, setConnected] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (publicRoutes.has(pathname)) return;
    const ws = new WebSocket("ws://localhost:8000/ws/default_user");
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === "ingestion_complete") {
          setNotice(`${message.paper_title || "Paper"} is ready in your graph.`);
        }
      } catch {
        // Ignore non-JSON keepalive messages.
      }
    };
    return () => ws.close();
  }, [pathname]);

  if (publicRoutes.has(pathname)) return <>{children}</>;

  async function logout() {
    await fetch("/api/auth", { method: "DELETE" });
    router.push("/");
    router.refresh();
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 border-r border-slate-200 bg-white lg:flex lg:flex-col">
        <Link href="/dashboard" className="flex h-20 items-center gap-3 border-b border-slate-100 px-6">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-slate-950 text-white"><Sparkles size={18} /></span>
          <span>
            <span className="block text-base font-semibold tracking-tight">PaperMind</span>
            <span className="block text-xs text-slate-500">Research intelligence</span>
          </span>
        </Link>
        <nav className="flex-1 space-y-1 p-4">
          <p className="mb-3 px-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Workspace</p>
          {navItems.map((item) => {
            const active = pathname === item.path;
            return (
              <Link key={item.path} href={item.path} className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                active ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"
              )}>
                <item.icon size={17} />{item.name}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-slate-100 p-4">
          <Button variant="ghost" className="w-full justify-start" onClick={logout}><LogOut size={16} /> Sign out</Button>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 flex h-20 items-center justify-between border-b border-slate-200 bg-white/90 px-5 backdrop-blur md:px-8">
          <div>
            <p className="text-sm font-medium">Personal research workspace</p>
            <p className="text-xs text-slate-500">Graph updates remain tied to your uploaded corpus.</p>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant={connected ? "success" : "warning"}>
              <span className={cn("mr-2 h-1.5 w-1.5 rounded-full", connected ? "bg-emerald-500" : "bg-amber-500")} />
              {connected ? "Live sync" : "API offline"}
            </Badge>
            <Button variant="outline" size="icon" aria-label="Notifications"><Bell size={16} /></Button>
          </div>
        </header>
        {notice && <div className="border-b border-emerald-100 bg-emerald-50 px-8 py-2 text-sm text-emerald-800">{notice}</div>}
        <main className="min-h-[calc(100vh-5rem)]">{children}</main>
      </div>
    </div>
  );
}
