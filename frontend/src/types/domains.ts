export interface TutorialSection {
  title: string;
  agent: string | null;
  api_refs?: string[];
}

export interface TutorialMeta {
  id: string;
  level: number;
  title: string;
  description: string;
  badge?: string;
  workflow: string | null;
  sections: TutorialSection[];
  apis: string[];
}

export interface WorkflowRef {
  name: string;
  description: string;
}

export interface ApiRefMeta {
  tutorial_id: string;
  tutorial_title: string;
  section_index: number;
  section_title: string;
}

export interface ApiDocMeta {
  id: string;
  title: string;
  description: string;
  file: string;
  referenced_by?: ApiRefMeta[];
}

export interface DomainMeta {
  id: string;
  title: string;
  description: string;
  color: string;
  icon: string;
  status: "active" | "coming_soon";
  tutorials: TutorialMeta[];
  workflows: WorkflowRef[];
  apis: ApiDocMeta[];
}

export interface TutorialSectionDetail extends TutorialSection {
  markdown: string;
  api_refs: string[];
}

export interface TutorialDetail {
  id: string;
  level: number;
  title: string;
  description: string;
  badge?: string;
  workflow: string | null;
  sections: TutorialSectionDetail[];
  apis: string[];
  domain_id: string;
  domain_title: string;
  domain_color: string;
  dag: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null;
}
