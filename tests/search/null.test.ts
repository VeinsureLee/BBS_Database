import { describe, it, expect } from 'vitest';
import { NullSearch } from '../../src/search/null.js';
import { NotImplementedError } from '../../src/search/types.js';
import { createSearch } from '../../src/search/index.js';

describe('NullSearch', () => {
  it('reports kind="null"', () => {
    const s = new NullSearch();
    expect(s.kind).toBe('null');
  });

  it('throws NotImplementedError on routeIntent', async () => {
    const s = new NullSearch();
    await expect(s.routeIntent('张三老师')).rejects.toBeInstanceOf(NotImplementedError);
  });

  it('throws NotImplementedError on threadsByMeaningBoard', async () => {
    const s = new NullSearch();
    await expect(s.threadsByMeaningBoard(42)).rejects.toBeInstanceOf(NotImplementedError);
  });

  it('throws NotImplementedError on suggestCrawlTargets (by meaning board)', async () => {
    const s = new NullSearch();
    await expect(s.suggestCrawlTargets({ meaningBoardId: 1 })).rejects.toBeInstanceOf(NotImplementedError);
  });

  it('throws NotImplementedError on suggestCrawlTargets (by query)', async () => {
    const s = new NullSearch();
    await expect(s.suggestCrawlTargets({ query: 'x' })).rejects.toBeInstanceOf(NotImplementedError);
  });

  it('error message mentions search.kind=null on all methods', async () => {
    const s = new NullSearch();
    const pattern = /search\.kind=null/;
    await expect(s.routeIntent('x')).rejects.toThrow(pattern);
    await expect(s.threadsByMeaningBoard(1)).rejects.toThrow(pattern);
    await expect(s.suggestCrawlTargets({ query: 'x' })).rejects.toThrow(pattern);
  });
});

describe('createSearch', () => {
  it("returns NullSearch when kind='null'", () => {
    const s = createSearch({ kind: 'null' });
    expect(s.kind).toBe('null');
    expect(s).toBeInstanceOf(NullSearch);
  });
});
