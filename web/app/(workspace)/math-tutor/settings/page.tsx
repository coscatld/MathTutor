import { Suspense } from "react";
import SettingsPanel from "@/features/math-tutor/desktop/components/SettingsPanel";

export default function MathTutorSettingsPage() {
  return <Suspense fallback={null}><SettingsPanel /></Suspense>;
}
