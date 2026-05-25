import type React from "react";

export interface DocSection {
  id: string;
  title: string;
  icon: React.ElementType;
  searchText: string;
  content: React.ReactNode;
  subsections?: { id: string; title: string }[];
}

export interface CodeBlockProps {
  code: string;
  lang?: string;
  showLineNumbers?: boolean;
}

export interface CalloutProps {
  children: React.ReactNode;
  variant?: "info" | "warning" | "tip" | "config" | "troubleshoot";
  title?: string;
}

export interface DocsTableProps {
  headers: string[];
  rows: string[][];
}

export interface QuickRefCardProps {
  title: string;
  items: { label: string; value: string }[];
}

export interface StepGuideProps {
  steps: { title: string; children: React.ReactNode }[];
}

export interface SectionHeadingProps {
  icon?: React.ElementType;
  children: React.ReactNode;
  level?: 2 | 3 | 4;
}
