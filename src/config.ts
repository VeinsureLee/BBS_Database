import 'dotenv/config';
import { resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '..');

function required(name: string): string {
  const v = process.env[name];
  if (!v) {
    throw new Error(
      `Missing env var ${name}. Copy BBS_Database/.env.example to .env and fill in the value.`,
    );
  }
  return v;
}

export const config = {
  dataRoot: resolve(ROOT, 'data', 'crawler.db'),
  structureDb: resolve(ROOT, 'data', 'crawler.db', 'structure.db'),
  forumsRoot: resolve(ROOT, 'data', 'crawler.db', 'forums'),

  neo4j: {
    uri: process.env.NEO4J_URI ?? 'bolt://localhost:7687',
    user: process.env.NEO4J_USER ?? 'neo4j',
    password: required('NEO4J_PASSWORD'),
    database: process.env.NEO4J_DATABASE ?? 'neo4j',
  },
} as const;
