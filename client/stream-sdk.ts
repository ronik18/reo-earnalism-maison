/** Official Cloudflare iframe SDK, loaded only for an enabled video action. */
export interface StreamPlayerAPI {
  currentTime: number;
  duration: number;
  paused: boolean;
  controls: boolean;
  play(): Promise<void>;
  pause(): void;
  addEventListener(type: string, handler: () => void): void;
  removeEventListener(type: string, handler: () => void): void;
}
export type StreamFactory = (frame: HTMLIFrameElement) => StreamPlayerAPI;
declare global { interface Window { Stream?: StreamFactory } }
let loading: Promise<StreamFactory> | undefined;
export function loadStreamSDK(): Promise<StreamFactory> {
  if (typeof window.Stream === "function") return Promise.resolve(window.Stream);
  if (!loading) loading = new Promise<StreamFactory>((resolve, reject) => {
    const script = document.createElement("script");
    const finish = (error?: Error) => {
      clearTimeout(timer); script.onload = null; script.onerror = null;
      if (error || typeof window.Stream !== "function") {
        script.remove(); reject(error || new Error("media_retry"));
      } else resolve(window.Stream);
    };
    const timer = window.setTimeout(() => finish(new Error("media_retry")), 10000);
    script.src = "https://embed.cloudflarestream.com/embed/sdk.latest.js";
    script.async = true;
    script.referrerPolicy = "no-referrer";
    script.onload = () => finish();
    script.onerror = () => finish(new Error("media_retry"));
    document.head.append(script);
  }).catch(error => { loading = undefined; throw error; });
  return loading;
}
