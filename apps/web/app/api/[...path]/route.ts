import { NextRequest } from "next/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const forwardedRequestHeaders = [
  "accept",
  "content-type",
  "cookie",
  "x-csrf-token",
  "origin",
  "authorization",
  "last-event-id",
  "idempotency-key",
  "x-request-id",
];
const forwardedResponseHeaders = [
  "content-type",
  "content-disposition",
  "cache-control",
  "location",
  "retry-after",
  "www-authenticate",
  "x-request-id",
  "x-accel-buffering",
];
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const origin =
    process.env.API_INTERNAL_URL ||
    process.env.INTERNAL_API_BASE_URL ||
    "http://localhost:8000";
  const target = new URL(
    `/api/${path.map(encodeURIComponent).join("/")}`,
    origin,
  );
  target.search = request.nextUrl.search;
  const headers = new Headers();
  for (const name of forwardedRequestHeaders) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    redirect: "manual",
    cache: "no-store",
    signal: request.signal,
  };
  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
    init.duplex = "half";
  }
  try {
    const upstream = await fetch(target, init);
    const responseHeaders = new Headers({ "Cache-Control": "no-store" });
    for (const name of forwardedResponseHeaders) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    for (const cookie of upstream.headers.getSetCookie())
      responseHeaders.append("set-cookie", cookie);
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      {
        detail:
          "The API service is unavailable. Check the backend service and try again.",
      },
      { status: 502 },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
  proxy as OPTIONS,
  proxy as HEAD,
};
