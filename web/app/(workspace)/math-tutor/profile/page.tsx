import {Suspense} from "react";
import LearningProfilePanel from "@/features/math-tutor/desktop/components/LearningProfilePanel";

export default function LearningProfilePage() {
  return <Suspense fallback={<p className="p-6">正在读取学习画像…</p>}><LearningProfilePanel /></Suspense>;
}
