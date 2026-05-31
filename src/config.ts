import 'dotenv/config';
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

function required(name: string): string {
  const v = process.env[name];
  if (!v) {
    throw new Error(
      `Missing env var ${name}. Copy BBS_Database/.env.example to .env and fill in the value.`,
    );
  }
  return v;
}

/**
 * @deprecated Bridge while migrating to createDatabase(). Reads process.env at
 * module load time, which couples consumers to the global environment. Prefer
 * `parseEnv(process.env)` + `createDatabase(...)`. Will be removed once all
 * call sites are migrated (see plan Task 17).
 */
export const config = {
  dataRoot: DEFAULT_DATA_ROOT,
  structureDb: resolve(DEFAULT_DATA_ROOT, 'structure.db'),
  forumsRoot: resolve(DEFAULT_DATA_ROOT, 'forums'),
  neo4j: {
    uri: process.env.NEO4J_URI ?? 'bolt://localhost:7687',
    user: process.env.NEO4J_USER ?? 'neo4j',
    password: required('NEO4J_PASSWORD'),
    database: process.env.NEO4J_DATABASE ?? 'neo4j',
  },
} as const;
