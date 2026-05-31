import neo4j, { type Driver, type Session } from 'neo4j-driver';
import { config as legacyConfig } from '../config.js';

export interface Neo4jConfig {
  uri: string;
  user: string;
  password: string;
  database: string;
}

export interface DriverHandle {
  driver: Driver;
  database: string;
  session(): Session;
  withSession<T>(fn: (s: Session) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

export function createDriver(cfg: Neo4jConfig): DriverHandle {
  const driver = neo4j.driver(
    cfg.uri,
    neo4j.auth.basic(cfg.user, cfg.password),
    { disableLosslessIntegers: true },
  );
  const handle: DriverHandle = {
    driver,
    database: cfg.database,
    session: () => driver.session({ database: cfg.database }),
    async withSession<T>(fn: (s: Session) => Promise<T>): Promise<T> {
      const s = handle.session();
      try {
        return await fn(s);
      } finally {
        await s.close();
      }
    },
    close: () => driver.close(),
  };
  return handle;
}

// --- DEPRECATED bridge: existing module-singleton API. Plan Task 17 removes it. ---

let _driver: Driver | null = null;

/** @deprecated use createDriver(cfg) and hold the instance. */
export function getDriver(): Driver {
  if (_driver) return _driver;
  _driver = neo4j.driver(
    legacyConfig.neo4j.uri,
    neo4j.auth.basic(legacyConfig.neo4j.user, legacyConfig.neo4j.password),
    { disableLosslessIntegers: true },
  );
  return _driver;
}

/** @deprecated use createDriver(cfg).session(). */
export function session(): Session {
  return getDriver().session({ database: legacyConfig.neo4j.database });
}

/** @deprecated use createDriver(cfg).withSession(...). */
export async function withSession<T>(fn: (s: Session) => Promise<T>): Promise<T> {
  const s = session();
  try {
    return await fn(s);
  } finally {
    await s.close();
  }
}

/** @deprecated use createDriver(cfg).close(). */
export async function closeDriver(): Promise<void> {
  if (_driver) {
    await _driver.close();
    _driver = null;
  }
}
