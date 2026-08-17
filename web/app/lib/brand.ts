import brandConfig from "../../brand.config.js";

export const BRAND = {
  name: brandConfig.name,
  displayName: brandConfig.displayName,
  description: brandConfig.description,
  tagline: brandConfig.tagline,
  organization: brandConfig.organization,
  version: brandConfig.version,
} as const;

export const API_CONFIG = {
  clientIdHeader: brandConfig.api.clientIdHeader,
  clientIdKey: brandConfig.api.clientIdKey,
} as const;
