export const THEME_BOOTSTRAP = `(()=>{try{const s=localStorage.getItem('judah-theme');const m=window.matchMedia('(prefers-color-scheme: dark)').matches;document.documentElement.dataset.theme=s||(m?'dark':'light');}catch(e){document.documentElement.dataset.theme='light';}})();`;

export function buildContentSecurityPolicy(themeHash: string, sandboxChat = false): string {
  const scriptSources = ["'self'", `'sha256-${themeHash}'`];
  const connectSources = ["'self'"];
  const frameSources = ["'none'"];
  const imageSources = ["'self'", "data:", "blob:"];

  if (sandboxChat) {
    scriptSources.push(
      "https://js-na1.hs-scripts.com",
      "https://js.usemessages.com",
      "https://static.hsappstatic.net",
    );
    connectSources.push("https://*.hubspot.com", "https://*.hubapi.com", "wss://*.hubspot.com");
    frameSources.splice(0, 1, "https://*.hubspot.com");
    imageSources.push("https://*.hubspot.com", "https://*.hubspotusercontent-na1.net");
  }

  return [
    "default-src 'self'",
    `script-src ${scriptSources.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src ${imageSources.join(" ")}`,
    "font-src 'self' data:",
    `connect-src ${connectSources.join(" ")}`,
    `frame-src ${frameSources.join(" ")}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}
