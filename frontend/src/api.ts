export type RecordData = { id: string; [key: string]: any };
export type Snapshot = { [key: string]: RecordData[] | any };
export async function api<T = any>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const form = body instanceof FormData;
  const response = await fetch("/api" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    headers:
      body !== undefined && !form ? { "Content-Type": "application/json" } : {},
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  const value = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = value?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : response.status === 422
          ? "تحقق من الحقول المطلوبة وصيغة البيانات"
          : "تعذر إتمام الطلب",
    );
  }
  return value as T;
}
