import Link from "next/link";
import { AuthKeyboardScope } from "@/components/auth/auth-keyboard-scope";
import { cn } from "@/lib/utils";

const clerkSharedVariables = {
  colorPrimary: "#29b7b1",
  colorPrimaryForeground: "#071013",
  colorNeutral: "#3a4653",
  colorForeground: "#ece6dc",
  colorMutedForeground: "#9e9a92",
  colorBackground: "transparent",
  colorInput: "rgba(255, 255, 255, 0.02)",
  colorInputForeground: "#ece6dc",
  colorDanger: "#de7068",
  fontFamily: "var(--font-sans-stack)",
  fontFamilyButtons: "var(--font-sans-stack)"
};

export const clerkAuthAppearance = {
  options: {
    autoFocus: false,
    elevation: "flush",
    socialButtonsPlacement: "top",
    socialButtonsVariant: "blockButton",
    unsafe_disableDevelopmentModeWarnings: true
  },
  variables: {
    ...clerkSharedVariables,
    borderRadius: "0rem",
    spacing: "1rem"
  },
  elements: {
    rootBox: "w-full",
    cardBox: "velora-auth-card-box w-full",
    card: "velora-auth-card border-0 bg-transparent px-0 py-0 text-foreground",
    header: "hidden",
    footer: "hidden",
    main: "velora-auth-main w-full",
    form: "velora-auth-form w-full",
    socialButtons: "w-full",
    socialButtonsBlockButton:
      "velora-social-provider-button h-12 !w-full rounded-none border border-white/10 bg-white/[0.02] px-4 text-foreground shadow-none transition-colors hover:border-primary/40 hover:bg-white/[0.04]",
    socialButtonsProviderIcon: "velora-social-provider-icon",
    socialButtonsBlockButtonText: "font-medium text-foreground",
    dividerRow: "velora-auth-divider",
    dividerLine: "bg-white/10",
    dividerText: "px-3 text-[10px] uppercase tracking-[0.32em] text-muted-foreground",
    formFieldRow: "velora-auth-form-row w-full",
    formField: "velora-auth-form-field w-full",
    formFieldErrorText: "velora-auth-field-feedback",
    formFieldLabel: "text-[10px] uppercase tracking-[0.28em] text-muted-foreground",
    formFieldInputGroup: "relative",
    formFieldInput:
      "velora-auth-input !w-full rounded-none bg-transparent px-0 pr-12 text-base text-foreground placeholder:text-muted-foreground [&[type='checkbox']]:h-4 [&[type='checkbox']]:w-4 [&[type='checkbox']]:min-h-4 [&[type='checkbox']]:min-w-4 [&[type='checkbox']]:rounded-sm [&[type='checkbox']]:p-0",
    formFieldInputShowPasswordButton: "velora-auth-password-toggle",
    formFieldInputShowPasswordIcon: "velora-auth-password-toggle-icon",
    formButtonPrimary:
      "velora-auth-submit !flex h-12 !w-full items-center justify-center rounded-none bg-primary px-5 text-center text-sm font-semibold uppercase leading-none tracking-[0.28em] text-primary-foreground transition-all hover:opacity-95 [&_.cl-buttonArrowIcon]:hidden",
    formFieldAction: "hidden",
    footerActionText: "hidden",
    footerActionLink: "hidden",
    identityPreviewText: "text-foreground",
    identityPreviewEditButton: "text-primary hover:text-primary/80",
    formResendCodeLink: "text-primary hover:text-primary/80",
    otpCodeField: "velora-auth-otp-field w-full",
    otpCodeFieldInputContainer: "velora-auth-otp-container w-full",
    otpCodeFieldInputs: "velora-auth-otp-inputs",
    otpCodeFieldInput: "velora-auth-otp-input",
    alertIcon: "velora-auth-alert-icon",
    alertText: "text-sm text-destructive",
    alertClerkError:
      "velora-auth-alert border border-destructive/30 bg-destructive/10 px-3 py-2"
  }
};

const defaultSupportItems = [
  {
    label: "Start with artwork",
    copy: "Bring in finished designs, mockups, and product ideas that are ready for listing work."
  },
  {
    label: "Keep setup reusable",
    copy: "Saved product setups keep the right store, product details, and defaults together."
  },
  {
    label: "Send with confidence",
    copy: "Leave with polished product details, images, pricing, and everything needed for the next step."
  }
] as const;

export function AuthShell({
  eyebrow,
  title,
  description,
  footer,
  controls,
  panelContext,
  panelTone = "default",
  panelLabel = "Account access",
  supportItems = defaultSupportItems,
  children
}: {
  eyebrow: string;
  title: string;
  description: string;
  footer?: React.ReactNode;
  controls?: React.ReactNode;
  panelContext?: React.ReactNode;
  panelTone?: "default" | "setup";
  panelLabel?: string;
  supportItems?: ReadonlyArray<{
    label: string;
    copy: string;
  }>;
  children: React.ReactNode;
}) {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[radial-gradient(circle_at_14%_18%,_rgba(41,183,177,0.14),_transparent_24%),radial-gradient(circle_at_84%_10%,_rgba(138,155,255,0.08),_transparent_24%),linear-gradient(180deg,_#06080c_0%,_#0a0d13_46%,_#090b10_100%)] text-foreground">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:120px_120px] opacity-[0.04]" />
        <div className="auth-drift absolute -left-24 top-16 h-72 w-72 rounded-full bg-primary/8 blur-3xl" />
      </div>

      <div className="relative grid min-h-screen lg:grid-cols-[minmax(0,1.08fr)_minmax(380px,460px)]">
        <section className="flex flex-col justify-between px-6 py-8 md:px-10 lg:px-14 lg:py-12">
          <div className="auth-rise">
            <Link href="/" className="inline-flex items-center gap-3">
              <span className="auth-display text-[2.15rem] leading-none text-foreground">Velora</span>
              <span className="mt-1 text-[10px] uppercase tracking-[0.32em] text-muted-foreground">
                Print-on-demand workspace
              </span>
            </Link>
            <div className="mt-20 max-w-3xl">
              <div className="text-[10px] uppercase tracking-[0.34em] text-primary/80">{eyebrow}</div>
              <h1 className="auth-display mt-6 max-w-3xl text-5xl leading-[0.92] text-foreground md:text-7xl lg:text-[5rem]">
                {title}
              </h1>
              <p className="mt-6 max-w-xl text-[15px] leading-7 text-muted-foreground md:text-base">
                {description}
              </p>
            </div>
          </div>

          <div className="auth-rise-delay grid gap-5 pt-12 text-sm text-muted-foreground md:grid-cols-3">
            {supportItems.map((item) => (
              <div key={item.label} className="border-t border-border/80 pt-4">
                <div className="text-[10px] uppercase tracking-[0.28em] text-primary/80">
                  {item.label}
                </div>
                <p className="mt-3 leading-6 text-muted-foreground">{item.copy}</p>
              </div>
            ))}
          </div>
        </section>

        <section
          className={cn(
            "auth-panel flex border-t px-6 py-10 md:px-10 lg:border-t-0 lg:px-12 lg:py-12",
            panelTone === "setup"
              ? "border-primary/25 bg-primary/[0.025]"
              : "border-border/80"
          )}
        >
          <div
            aria-hidden="true"
            className="absolute inset-y-0 left-0 hidden w-px bg-border/80 lg:block"
          />
          <AuthKeyboardScope className="relative z-10 flex w-full flex-col justify-center">
            <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-border/80 pb-4">
              <div className="text-[10px] uppercase tracking-[0.34em] text-muted-foreground">
                {panelLabel}
              </div>
              {controls ? <div className="shrink-0">{controls}</div> : null}
            </div>
            {panelContext}
            <div className="w-full max-w-md space-y-5">
              {children}
              {footer ? (
                <div className="border-t border-border/80 pt-4 text-sm text-muted-foreground">
                  {footer}
                </div>
              ) : null}
            </div>
          </AuthKeyboardScope>
        </section>
      </div>
    </main>
  );
}
