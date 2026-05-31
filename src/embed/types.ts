export interface Embedder {
  readonly model: string;
  readonly dims: number;
  embed(texts: string[]): Promise<Float32Array[]>;
}

export type EmbedderKind = 'stub' | 'dashscope' | 'openai';
