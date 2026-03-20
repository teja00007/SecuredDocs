export interface User {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  roles: string[];
  teams: string[];
  created_at: string;
  company_id?: string | null;
  is_super_admin?: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Collection {
  id: string;
  name: string;
  description: string | null;
  owner_id: string;
  is_public: boolean;
  document_count: number;
  created_at: string;
}

export interface Document {
  id: string;
  filename: string;
  file_type: string;
  file_size: number | null;
  visibility: "public" | "team" | "channel" | "confidential";
  status: "pending" | "processing" | "ready" | "failed" | "flagged" | "compliance_blocked" | "embedding_failed";
  owner_id: string;
  collection_id: string | null;
  chunk_count: number;
  chunking_strategy: string | null;
  created_at: string;
}

export interface Channel {
  id: string;
  name: string;
  type: string;
  team_id?: string | null;
}

export interface Team {
  id: string;
  name: string;
  description: string | null;
  created_by: string;
  member_count: number;
  created_at: string;
}

export interface TeamDetail extends Team {
  members: User[];
}

export interface Source {
  document_id: string;
  filename: string;
  chunk_text: string;
  page_number: number | null;
  score: number;
  is_stale?: boolean;
  days_since_update?: number | null;
}

export interface QueryResponse {
  answer: string;
  sources: Source[];
  confidence_score: number;
  confidence_label: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
}

export interface Conversation {
  id: string;
  title: string;
  collection_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ConversationMessage[];
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[] | null;
  feedback: number | null;
  created_at: string;
}
