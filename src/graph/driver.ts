import neo4j, { type Driver, type Session } from 'neo4j-driver';

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
