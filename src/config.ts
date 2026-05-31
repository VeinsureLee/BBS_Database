import { resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '..');
const DEFAULT_DATA_ROOT = resolve(ROOT, 'data', 'crawler.db');

export interface DatabaseConfig {
  dataRoot: string;
  neo4j: {
    uri: string;
    user: string;
    password: string;
    database: string;
  };
}

export function parseEnv(env: NodeJS.ProcessEnv | Record<string, string | undefined>): DatabaseConfig {
  const password = env.NEO4J_PASSWORD;
  if (!password) {
    throw new Error(
      'Missing env var NEO4J_PASSWORD. Copy BBS_Database/.env.example to .env and fill in the value.',
    );
  }
  return {
    dataRoot: env.BBS_DATA_ROOT ?? DEFAULT_DATA_ROOT,
    neo4j: {
      uri: env.NEO4J_URI ?? 'bolt://localhost:7687',
      user: env.NEO4J_USER ?? 'neo4j',
      password,
      database: env.NEO4J_DATABASE ?? 'neo4j',
    },
  };
}

