// Website: show the newest verified launcher build (public endpoint, no token, works from a browser page).
import { MetallicApi } from "../metallic-api.mjs";

const api = new MetallicApi({ baseUrl: "https://metallic-api.example:8476" });
const channel = await api.getRelease("stable");
const launcher = channel.components.find((c) => c.name === "launcher");
console.log(launcher ? `Metallic ${launcher.version} (${launcher.released})` : "No release yet");
