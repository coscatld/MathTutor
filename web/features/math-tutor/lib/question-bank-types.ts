/** Question bank v1 wire types (see docs/QUESTION_BANK_SPEC.md). */

export type LearnerStage = "primary" | "middle" | "high";

export interface LearnerSettings {
  stage: LearnerStage | null;
  grade: number | null;
  stages: { stage: LearnerStage; label: string; grades: number[] }[];
}

export interface BankPointSummary { code: string; title: string; problem_count: number; demo_count: number }
export interface BankUnit { code: string; title: string; points: BankPointSummary[] }
export interface BankTerm { code: string; stage: LearnerStage; grade: number; order: number; label: string; book: string; units: BankUnit[] }

export interface QuestionBank {
  version: string;
  stage: LearnerStage | null;
  source_note: string;
  terms: BankTerm[];
}

export interface BankProblem { id: string; text: string; display_latex: string; family: string; difficulty: number }
export interface BankDemo { title: string; request: string }

export interface BankPointDetail {
  point: { code: string; title: string; term: string; unit: string };
  problems: BankProblem[];
  demos: BankDemo[];
  note: string;
}
