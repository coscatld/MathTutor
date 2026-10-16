/** Question bank v1 wire types (see docs/QUESTION_BANK_SPEC.md). */

export type LearnerStage = "primary" | "middle" | "high";

export interface LearnerSettings {
  stage: LearnerStage | null;
  grade: number | null;
  stages: { stage: LearnerStage; label: string; grades: number[] }[];
}

export interface BankPointSummary { code: string; title: string; problem_count: number; reference_count?: number; total_count?: number; demo_count: number }
export interface BankUnit { code: string; title: string; points: BankPointSummary[] }
export interface BankTerm { code: string; stage: LearnerStage; grade: number; recommended_grades?: number[]; order: number; label: string; book: string; units: BankUnit[] }

export interface QuestionBank {
  version: string;
  stage: LearnerStage | null;
  source_note: string;
  terms: BankTerm[];
}

export interface BankProblem { id: string; text: string; display_latex: string; family: string; difficulty: number }
export interface BankDemo { title: string; request: string }
/** A worked reference answer does not establish automatic student-step grading. */
export interface BankReferenceProblem {
  id: string;
  text: string;
  reference_answer: string;
  explanation: string;
  difficulty: 1 | 2 | 3;
  category: "基础与应用" | "综合应用" | "推理与证明";
  verification: { mode: "reference"; answer_check: string | null; student_steps_auto_verified: false };
}

export interface BankPointDetail {
  point: { code: string; title: string; term: string; unit: string };
  problems: BankProblem[];
  reference_problems?: BankReferenceProblem[];
  demos: BankDemo[];
  note: string;
}
