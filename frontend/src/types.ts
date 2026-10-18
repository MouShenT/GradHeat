export type DataRow = Record<string, unknown> & { id: string; unit: string; year: number }
export interface ProgrammeDecisionInputs {
  threshold: number | null; threshold_year: number | null; threshold_basis?: string
  ordinary_quota: number | null; capacity_proxy: number | null; capacity_year: number | null
  retest_weights: Record<string, number>; retest_weights_year?: number | null
  admitted_scores: { year?: number; population?: string; mean?: number; minimum?: number; maximum?: number }
}
export interface CommunityAdmissionSample {
  program_name?: string | null; year?: number | null; exam_text?: string | null
  record_count?: number | null; admitted_sample_count?: number | null; unadmitted_retest_sample_count?: number | null
  observed_retest_list_minimum?: number | null; admitted_total_minimum?: number | null
  distribution_population?: string | null; verification_state?: string | null
}
export interface Programme extends DataRow {
  department?: string; group?: string; major_name: string; major_code: string
  directions: string[]; subjects: string[]; degree_type: string; mode: string
  plan_text?: string; plan_status?: string; ordinary_quota?: number | null; campus?: string
  scope?: string
  eligible_11408: boolean | null
  decision_inputs?: ProgrammeDecisionInputs
}
export interface Admissions {
  target_year: number; data_as_of: string; last_checked?: string
  units: { name: string; group: string }[]; programmes: Programme[]; history: DataRow[]
  cutoff_rows: DataRow[]; admission_groups: DataRow[]
  historical_alignment?: Record<string, { matched: string[]; ambiguous: string[] }>
  official_notes?: { unit: string; year: number; note: string }[]
  counts: { units: number; programmes: number; matched_programmes: number; history_rows: number }
}
export interface OverviewRow extends DataRow {
  major_name: string; major_code: string; reported_plan: number | null; plan_text: string
  history: DataRow[]; related_rules: { year: number; scope: string; statements: string[]; historical: boolean }[]
  background: { friendliness: string; note: string }
}
export interface Dashboard { data_version: string; programmes: OverviewRow[]; chart_policy: string }
export interface HeatPlatform {
  platform: string; label: string; unique_contents: number; sampling_state: string; observed_until?: string | null
  metrics: Record<string, { sum_known_values: number | null; known_contents: number; unknown_contents: number }>
  query_groups: { query: string; actual_sort: string | null }[]; health?: { state: string }
}
export interface Heat { unit: string; checked_at?: string; platforms: HeatPlatform[]; note: string; read_state?: string; heat_value?: number | null; basis?: string; dossier_version?: string }
export interface Task { task_id: string; status: string; result?: unknown; error?: unknown }
export interface Column { key: string; label: string; width: number; value: (row: DataRow) => unknown }
