import { KoiApi } from "./api.js";

if (!window.__HUB__) {
  KoiApi.getAgentBackends().catch(error => console.warn("CLI discovery:", error.message));
}
