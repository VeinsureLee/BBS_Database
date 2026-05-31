import type { VisualizeProvider } from './types.js';
import { Neo4jBrowserProvider } from './neo4j-browser.js';

export type VisualizeConfig = { kind: 'neo4j-browser'; url?: string };

export interface VisualizeDeps {
  neo4j: { uri: string; user: string; database: string };
}

export function createVisualize(
  cfg: VisualizeConfig,
  deps: VisualizeDeps,
): VisualizeProvider {
  switch (cfg.kind) {
    case 'neo4j-browser':
      return new Neo4jBrowserProvider(
        cfg.url !== undefined
          ? { neo4j: deps.neo4j, url: cfg.url }
          : { neo4j: deps.neo4j },
      );
    default: {
      const _exhaustive: never = cfg.kind;
      throw new Error(`unknown visualize kind: ${_exhaustive as string}`);
    }
  }
}

export { Neo4jBrowserProvider } from './neo4j-browser.js';
export type { VisualizeProvider, VisualizeInfo, VisualizeKind } from './types.js';
