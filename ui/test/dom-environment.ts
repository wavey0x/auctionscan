import { builtinEnvironments } from "vitest/environments";
import type { Environment } from "vitest/environments";

export default {
  name: "dom-with-native-fetch",
  transformMode: "web",
  async setup(global, options) {
    // React Router uses Node's Request, whose signal must come from the same
    // implementation. Keep its abort globals when jsdom installs DOM globals.
    const { AbortController, AbortSignal } = global;
    const environment = await builtinEnvironments.jsdom.setup(global, options);
    Object.assign(global, { AbortController, AbortSignal });
    return environment;
  },
} satisfies Environment;
