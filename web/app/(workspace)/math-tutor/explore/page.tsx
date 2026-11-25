import ExplorationWorkbench from "@/features/math-tutor/exploration/ExplorationWorkbench";

export default async function ExplorePage({ searchParams }: { searchParams: Promise<{ topic?: string | string[] }> }) {
  const { topic } = await searchParams;
  return <ExplorationWorkbench initialTopic={typeof topic === "string" ? topic.slice(0, 200) : ""} />;
}
