/** Tipos compartidos de la API del backend HacheCode Agent V4. */

export interface Me {
  username: string;
  agent_uid: number;
  is_admin: boolean;
  csrf_token: string;
  expires_at: string;
}

export interface Project {
  id: number;
  name: string;
  created_at?: string | null;
  exists?: boolean;
  path?: string;
}

export interface ProjectInfo {
  project: Project;
  exists: boolean;
  files: number;
  size_bytes: number;
  git: { repo_url: string | null; current_branch: string | null; default_branch: string | null };
}

export interface Conversation {
  id: number;
  user_id: number;
  project_id: number | null;
  provider: string;
  model: string;
  title: string;
  n_msgs?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ToolCallRow {
  id: string;
  name: string;
  arguments: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | "tool";
  content: string | null;
  tool_calls?: ToolCallRow[] | null;
  tool_call_id?: string | null;
  name?: string | null;
  tokens_in?: number;
  tokens_out?: number;
  cost?: number;
}

export type PlanStatus = "pending" | "in_progress" | "done" | "failed" | "partial";

export interface PlanStep {
  title: string;
  status: PlanStatus;
}

export type TaskStatus =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface Task {
  id: number;
  status: TaskStatus;
  title: string;
  kind: string;
  project_id: number | null;
  conversation_id: number | null;
  steps: number;
  max_steps: number;
  error: string | null;
  result: string | null;
  created_at?: string;
  finished_at?: string | null;
  plan?: PlanStep[];
  zip_available?: boolean;
}

export interface TaskEvent {
  id: number;
  task_id: number;
  type: string; // plan | tool | notify | status | plan_incomplete | end
  data: Record<string, unknown>;
  created_at: string;
}

export interface ModelRow {
  id: string;
  context_window: number | null;
  max_output: number | null;
}

export interface ModelsResponse {
  provider: string;
  selected: string;
  models: ModelRow[];
  error?: string;
}

export interface ProviderRow {
  name: string;
  kind: string;
  base_url: string;
  enabled: boolean;
  has_key: boolean;
}

export interface TreeNode {
  name: string;
  type: "dir" | "file";
  size?: number;
  truncated?: boolean;
  children?: TreeNode[];
}

export interface FileContent {
  path: string;
  binary: boolean;
  content?: string;
  content_base64?: string;
  size: number;
  truncated: boolean;
}

export interface GitStatus {
  is_repo: boolean;
  status: string;
  remotes?: string;
  branch: string;
  repo_url: string;
  autopush?: boolean;
  allowed_branches?: string[];
}

export interface GitCommit {
  hash: string;
  author: string;
  date: string;
  subject: string;
}

export interface PushPreview {
  repo_url: string;
  branch: string;
  commits: { hash: string; subject: string }[];
  push_token: string;
  expires_in_s: number;
  warning?: string;
}

export interface UsageSummary {
  today_cost: number;
  totals: { pt: number; ct: number; tt: number; cost: number; calls: number };
  by_model: {
    provider: string;
    model: string;
    calls: number;
    pt: number;
    ct: number;
    tt: number;
    cost: number | null;
  }[];
}
