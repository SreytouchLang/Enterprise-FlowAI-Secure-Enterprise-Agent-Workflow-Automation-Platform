"use client";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState } from "react";
import { api, ApiError, setCsrfToken, User } from "@/lib/api";
import { CheckCircle2, X, AlertCircle } from "lucide-react";
type Toast = { id: number; message: string; error: boolean };
const ToastContext = createContext<(message: string, error?: boolean) => void>(
  () => {},
);
export const useToast = () => useContext(ToastContext);
export function useUser() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async ({ signal }) => {
      try {
        const user = await api<User>("/auth/me", { signal });
        signal.throwIfAborted();
        setCsrfToken(user.csrf_token);
        return user;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
}
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: (count, error) =>
              !(
                error instanceof ApiError &&
                [401, 403, 404].includes(error.status)
              ) && count < 1,
            refetchOnWindowFocus: false,
            staleTime: 15_000,
          },
        },
      }),
  );
  useEffect(() => {
    const expired = () => {
      setCsrfToken("");
      void client.cancelQueries();
      client.removeQueries({
        predicate: (query) => query.queryKey[0] !== "me",
      });
      client.getMutationCache().clear();
      client.setQueryData(["me"], null);
      setToasts([]);
    };
    window.addEventListener("ef-session-expired", expired);
    return () => window.removeEventListener("ef-session-expired", expired);
  }, [client]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  function toast(message: string, error = false) {
    const id = Date.now() + Math.random();
    setToasts((old) => [...old, { id, message, error }]);
    setTimeout(() => setToasts((old) => old.filter((t) => t.id !== id)), 7000);
  }
  return (
    <QueryClientProvider client={client}>
      <ToastContext.Provider value={toast}>
        {children}
        <div className="toast-stack" aria-live="polite">
          {toasts.map((t) => (
            <div
              key={t.id}
              role={t.error ? "alert" : "status"}
              className={`toast ${t.error ? "toast-error" : ""}`}
            >
              {t.error ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
              <span>{t.message}</span>
              <button
                aria-label="Dismiss notification"
                onClick={() =>
                  setToasts((old) => old.filter((x) => x.id !== t.id))
                }
              >
                <X size={16} />
              </button>
            </div>
          ))}
        </div>
      </ToastContext.Provider>
    </QueryClientProvider>
  );
}
