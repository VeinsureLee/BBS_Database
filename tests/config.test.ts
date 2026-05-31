import { describe, it, expect } from 'vitest';
import { parseEnv } from '../src/config.js';

describe('parseEnv', () => {
  it('parses minimal env (only NEO4J_PASSWORD required)', () => {
    const c = parseEnv({ NEO4J_PASSWORD: 'pw' });
    expect(c.neo4j.uri).toBe('bolt://localhost:7687');
    expect(c.neo4j.user).toBe('neo4j');
    expect(c.neo4j.password).toBe('pw');
    expect(c.neo4j.database).toBe('neo4j');
  });

  it('throws when NEO4J_PASSWORD missing', () => {
    expect(() => parseEnv({})).toThrow(/NEO4J_PASSWORD/);
  });

  it('honors NEO4J_URI / NEO4J_USER / NEO4J_DATABASE overrides', () => {
    const c = parseEnv({
      NEO4J_URI: 'bolt://remote:9999',
      NEO4J_USER: 'admin',
      NEO4J_PASSWORD: 'pw',
      NEO4J_DATABASE: 'bbs',
    });
    expect(c.neo4j.uri).toBe('bolt://remote:9999');
    expect(c.neo4j.user).toBe('admin');
    expect(c.neo4j.database).toBe('bbs');
  });

  it('honors BBS_DATA_ROOT override', () => {
    const c = parseEnv({ NEO4J_PASSWORD: 'pw', BBS_DATA_ROOT: '/tmp/x' });
    expect(c.dataRoot).toBe('/tmp/x');
  });
});
