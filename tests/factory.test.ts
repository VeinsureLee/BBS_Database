import { describe, it, expect } from 'vitest';
import { createDatabase } from '../src/factory.js';
import { NotImplementedError } from '../src/search/types.js';

describe('createDatabase wiring (no Neo4j calls)', () => {
  const cfg = {
    dataRoot: '/tmp/nonexistent',
    neo4j: { uri: 'bolt://localhost:7687', user: 'neo4j', password: 'pw', database: 'neo4j' },
  };

  it('returns an instance with graph / search / visualize / shutdown', async () => {
    const db = await createDatabase(cfg);
    expect(typeof db.graph.bootstrap).toBe('function');
    expect(typeof db.graph.sync).toBe('function');
    expect(typeof db.graph.ensureSchema).toBe('function');
    expect(db.search.kind).toBe('null');
    expect(db.visualize.kind).toBe('neo4j-browser');
    expect(typeof db.shutdown).toBe('function');
    await db.shutdown();
  });

  it('search defaults to NullSearch which throws NotImplemented', async () => {
    const db = await createDatabase(cfg);
    try {
      await expect(db.search.routeIntent('x')).rejects.toBeInstanceOf(NotImplementedError);
    } finally {
      await db.shutdown();
    }
  });

  it('visualize.info() returns expected http URL', async () => {
    const db = await createDatabase(cfg);
    try {
      const info = db.visualize.info();
      expect(info.url).toMatch(/^http:\/\//);
      expect(info.user).toBe('neo4j');
    } finally {
      await db.shutdown();
    }
  });
});
