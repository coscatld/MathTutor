import MathTutorPage from "@/features/math-tutor/components/MathTutorPage";

/**
 * Student MathTutor workspace (K12 guided math tutoring).
 * Route lives in the (workspace) group so it inherits the shared app shell;
 * the entire feature implementation is in web/features/math-tutor/.
 */
export default function MathTutorRoute() {
  return <MathTutorPage />;
}
