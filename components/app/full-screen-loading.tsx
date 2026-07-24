export function FullScreenLoading({
  label = "Preparing workspace",
  message = "Loading your access and workspace context."
}: {
  label?: string;
  message?: string;
}) {
  return (
    <main className="relative min-h-screen overflow-hidden bg-background text-foreground">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(255,255,255,0.02),transparent_38%)]" />

      <div className="relative flex min-h-screen items-center justify-center px-6">
        <div
          role="status"
          aria-live="polite"
          className="flex w-full max-w-sm flex-col items-center text-center"
        >
          <div className="mb-8 flex h-9 w-20 items-center justify-center gap-2 rounded-full border border-border bg-card/60 backdrop-blur-sm">
            <span className="h-2.5 w-2.5 rounded-full bg-primary/55 animate-jump-dot [animation-delay:0ms]" />
            <span className="h-2.5 w-2.5 rounded-full bg-primary/80 animate-jump-dot [animation-delay:150ms]" />
            <span className="h-2.5 w-2.5 rounded-full bg-primary animate-jump-dot [animation-delay:300ms]" />
          </div>

          <div className="auth-display mt-4 text-[2.75rem] leading-[0.94] text-foreground">
            Loading...
          </div>

          <div className="sr-only">{label}. {message}</div>
        </div>
      </div>
    </main>
  );
}
