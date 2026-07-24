type ClerkStatusCardProps = {
  mode: "sign-in" | "sign-up";
  missingEnv?: readonly string[];
};

export function ClerkStatusCard({ mode, missingEnv = [] }: ClerkStatusCardProps) {
  return (
    <div className="w-full max-w-md border-y border-white/10 py-8">
      <div className="mb-3 text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
        Sign-in setup required
      </div>
      <h1 className="auth-display mb-4 text-4xl leading-none text-foreground">
        Sign-in is not ready yet.
      </h1>
      <p className="text-sm leading-7 text-muted-foreground">
        Add the required sign-in keys to continue with the {mode === "sign-in" ? "sign-in" : "sign-up"} flow.
        Until then, Velora can still run in preview mode for local development.
      </p>
      {missingEnv.length > 0 ? (
        <div className="mt-6 border-t border-white/8 pt-5">
          <div className="text-[10px] uppercase tracking-[0.24em] text-muted-foreground">Missing settings</div>
          <div className="mt-3 space-y-1 font-mono text-xs text-foreground">
            {missingEnv.map((key) => (
              <div key={key}>{key}</div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
