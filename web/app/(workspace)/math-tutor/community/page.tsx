import { Suspense } from "react";
import CommunityPage from "@/features/math-tutor/community/CommunityPage";
import "@/features/math-tutor/community/community.css";

export default function CommunityRoute() { return <Suspense fallback={<p role="status" className="mt-page">正在读取社区…</p>}><CommunityPage /></Suspense>; }
