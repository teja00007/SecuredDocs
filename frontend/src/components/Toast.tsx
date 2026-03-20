"use client";

import {
  createContext, useCallback, useContext, useRef, useState, useEffect,
} from "react";

export type ToastType = "success" | "error" | "info" | "warning";

interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
  duration?: number;
}

interface ToastCtx {
  toast: (message: string, type?: ToastType, duration?: number) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  warn: (message: string) => void;
}

const ToastContext = createContext<ToastCtx | null>(null);

const ICONS: Record<ToastType, string> = {
  success: "✓",
  error:   "✕",
  info:    "ℹ",
  warning: "⚠",
};

const STYLES: Record<ToastType, string> = {
  success: "bg-emerald-600 text-white",
  error:   "bg-red-600 text-white",
  info:    "bg-indigo-600 text-white",
  warning: "bg-amber-500 text-white",
};

let _counter = 0;

function ToastItem({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Slide in
    const t1 = setTimeout(() => setVisible(true), 10);
    // Slide out
    const t2 = setTimeout(() => setVisible(false), (item.duration ?? 3500) - 300);
    // Remove
    const t3 = setTimeout(() => onDismiss(item.id), item.duration ?? 3500);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, [item, onDismiss]);

  return (
    <div
      className={`flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium shadow-lg cursor-pointer transition-all duration-300 ${STYLES[item.type]} ${
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"
      }`}
      onClick={() => onDismiss(item.id)}
    >
      <span className="shrink-0 flex h-5 w-5 items-center justify-center rounded-full bg-white/20 text-xs font-bold">
        {ICONS[item.type]}
      </span>
      <span className="flex-1">{item.message}</span>
      <button className="ml-1 shrink-0 opacity-70 hover:opacity-100 text-xs" onClick={() => onDismiss(item.id)}>✕</button>
    </div>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const toast = useCallback((message: string, type: ToastType = "info", duration = 3500) => {
    const id = ++_counter;
    setToasts(prev => [...prev.slice(-4), { id, type, message, duration }]);
  }, []);

  const ctx: ToastCtx = {
    toast,
    success: (m) => toast(m, "success"),
    error:   (m) => toast(m, "error", 5000),
    info:    (m) => toast(m, "info"),
    warn:    (m) => toast(m, "warning", 4000),
  };

  return (
    <ToastContext.Provider value={ctx}>
      {children}
      {/* Toast stack */}
      <div className="fixed bottom-5 right-5 z-[9999] flex flex-col gap-2 w-80 max-w-[calc(100vw-2.5rem)]" aria-live="polite">
        {toasts.map(t => (
          <ToastItem key={t.id} item={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastCtx {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
