import DesktopShell from "@/features/math-tutor/desktop/components/DesktopShell";
import StartupBoundary from "@/features/math-tutor/desktop/components/StartupBoundary";
import ToastProvider from "@/features/math-tutor/desktop/components/ToastProvider";

/**
 * MathTutor workspace shell — the product frame shared by the tutoring view,
 * offers, documents, memory and settings. Pure shell: navigation + readiness
 * status; all business logic lives in the backend bridge and the session
 * reducer.
 */
export default function MathTutorLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <StartupBoundary>
      <ToastProvider><DesktopShell>{children}</DesktopShell></ToastProvider>
    </StartupBoundary>
  );
}
