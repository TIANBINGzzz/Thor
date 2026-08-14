export type ModelOption = {
  id: string;
  modality: "text" | "multimodal";
};

export const MODELS: ModelOption[] = [
  { id: "deepseek-v4-flash", modality: "text" },
  { id: "deepseek-v4-pro", modality: "text" },
  { id: "qwen3.8-max", modality: "multimodal" },
  { id: "qwen3.7-plus", modality: "multimodal" },
];

export const DEFAULT_MODEL_ID = "deepseek-v4-flash";

export function isModelId(value: string): boolean {
  return MODELS.some((model) => model.id === value);
}
