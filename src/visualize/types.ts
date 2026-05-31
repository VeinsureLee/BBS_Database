export type VisualizeKind = 'neo4j-browser' | 'http-server' | 'static-export';

export interface VisualizeInfo {
  kind: VisualizeKind;
  /** Where to open in a browser (HTTP, NOT bolt). */
  url: string;
  user: string;
  database: string;
  /** One-liner pointer for an agent / user on what to look at. */
  hint: string;
}

export interface VisualizeProvider {
  readonly kind: VisualizeKind;
  info(): VisualizeInfo;
}
