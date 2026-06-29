import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.PAPERMIND_BACKEND_URL || "http://localhost:8000";

type RouteContext = { params: { path: string[] } };

function buildBackendUrl(path: string[], request: NextRequest) {
  const url = new URL(request.url);
  const backend = new URL(`${BACKEND_URL}/api/${path.join("/")}`);
  backend.search = url.search;
  return backend;
}

async function proxy(request: NextRequest, context: RouteContext) {
  const backendUrl = buildBackendUrl(context.params.path, request);

  try {
    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.delete("connection");
    headers.delete("content-length");

    const init: RequestInit & { duplex?: "half" } = {
      method: request.method,
      headers,
      cache: "no-store",
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = await request.arrayBuffer();
      init.duplex = "half";
    }

    const response = await fetch(backendUrl, init);
    const contentType = response.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
      const data = await response.json();
      return NextResponse.json(data, { status: response.status });
    }

    const text = await response.text();
    return NextResponse.json(
      {
        detail: text || `Backend request failed with status ${response.status}.`,
        upstream_status: response.status,
      },
      { status: response.status },
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Backend connection failed.";
    console.error(`PaperMind API proxy failed for ${backendUrl.toString()}`, error);
    return NextResponse.json(
      {
        detail: `PaperMind backend is unavailable: ${message}`,
        upstream_status: 502,
      },
      { status: 502 },
    );
  }
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}
