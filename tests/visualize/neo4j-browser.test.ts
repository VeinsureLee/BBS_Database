import { describe, it, expect } from 'vitest';
import { Neo4jBrowserProvider } from '../../src/visualize/neo4j-browser.js';
import { createVisualize } from '../../src/visualize/index.js';

describe('Neo4jBrowserProvider', () => {
  const neo4j = { uri: 'bolt://localhost:7687', user: 'neo4j', database: 'neo4j' };

  it('reports kind="neo4j-browser"', () => {
    const p = new Neo4jBrowserProvider({ neo4j });
    expect(p.kind).toBe('neo4j-browser');
  });

  it('derives http://localhost:7474 from bolt://localhost:7687', () => {
    const p = new Neo4jBrowserProvider({ neo4j });
    expect(p.info().url).toBe('http://localhost:7474');
  });

  it('passes through user and database', () => {
    const p = new Neo4jBrowserProvider({ neo4j });
    const i = p.info();
    expect(i.user).toBe('neo4j');
    expect(i.database).toBe('neo4j');
  });

  it('honors explicit url override', () => {
    const p = new Neo4jBrowserProvider({
      neo4j,
      url: 'http://example.com:7474',
    });
    expect(p.info().url).toBe('http://example.com:7474');
  });

  it('handles bolt://host with non-default port', () => {
    const p = new Neo4jBrowserProvider({
      neo4j: { ...neo4j, uri: 'bolt://10.0.0.5:7688' },
    });
    // Heuristic: replace bolt -> http, 7687 -> 7474; for other bolt ports, keep
    // user-overridable but default to http://host:7474.
    expect(p.info().url).toBe('http://10.0.0.5:7474');
  });

  it('hint mentions a starter Cypher query', () => {
    const p = new Neo4jBrowserProvider({ neo4j });
    expect(p.info().hint).toMatch(/MATCH/);
  });

  it('derives http://localhost:7474 from neo4j://localhost:7687 (routing scheme)', () => {
    const p = new Neo4jBrowserProvider({
      neo4j: { ...neo4j, uri: 'neo4j://localhost:7687' },
    });
    expect(p.info().url).toBe('http://localhost:7474');
  });
});

describe('createVisualize', () => {
  const deps = {
    neo4j: { uri: 'bolt://localhost:7687', user: 'neo4j', database: 'neo4j' },
  };

  it("returns Neo4jBrowserProvider when kind='neo4j-browser'", () => {
    const v = createVisualize({ kind: 'neo4j-browser' }, deps);
    expect(v).toBeInstanceOf(Neo4jBrowserProvider);
    expect(v.kind).toBe('neo4j-browser');
  });

  it('threads explicit url override through to provider', () => {
    const v = createVisualize(
      { kind: 'neo4j-browser', url: 'http://example.com:7474' },
      deps,
    );
    expect(v.info().url).toBe('http://example.com:7474');
  });
});
