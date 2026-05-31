export interface BootstrapStats {
  sites: number;
  forums: number;
  sub_forums: number;
  boards: number;
  edges: number;
  pruned_edges: number;
}

export interface SyncStats {
  boards_scanned: number;
  boards_with_threads: number;
  threads_synced: number;
  located_in_edges: number;
  posted_in_edges: number;
  months_seen: number;
}

export interface GraphOps {
  ensureSchema(): Promise<void>;
  bootstrap(): Promise<BootstrapStats>;
  sync(): Promise<SyncStats>;
}
