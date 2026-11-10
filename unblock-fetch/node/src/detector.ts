const ALWAYS_BLOCK_STATUS = new Set([403, 429]);
const CHALLENGE_STATUS = new Set([503]);
const CHALLENGE_MARKERS = new RegExp(
  "just a moment|checking your browser|verify you are (?:a )?human|attention required" +
    "|access denied|captcha|are you a robot|unusual traffic|enable javascript and cookies" +
    "|px-captcha|challenge-platform|cf-chl|_incapsula_|datadome|geo\\.captcha-delivery\\.com" +
    "|hcaptcha|g-recaptcha|cf-turnstile",
  "i",
);
const SCRIPT_OR_STYLE = /<(script|style|noscript)\b[\s\S]*?<\/\1>/gi;
const TAGS = /<[^>]+>/g;
const JS_REQUIRED = /enable javascript|requires javascript/i;
const EMPTY_SHELL_MAX_CHARS = 80;

function visibleText(html: string): string {
  return html
    .replace(SCRIPT_OR_STYLE, " ")
    .replace(TAGS, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

/** True for 403/429, a 503 or 2xx page with a challenge/CAPTCHA signature, or an empty JS shell.
 * A plain 404 or other error status is never a block. */
export function isBlocked(status: number | null | undefined, body: string): boolean {
  body = body || "";
  if (status != null && ALWAYS_BLOCK_STATUS.has(status)) return true;
  if (status != null && CHALLENGE_STATUS.has(status)) return CHALLENGE_MARKERS.test(body);
  if (status != null && !(status >= 200 && status < 300)) return false;
  if (CHALLENGE_MARKERS.test(body)) return true;
  const lowered = body.toLowerCase();
  if (lowered.includes("<html") || lowered.includes("<body") || lowered.includes("<div")) {
    return visibleText(body).length <= EMPTY_SHELL_MAX_CHARS;
  }
  if (JS_REQUIRED.test(body)) return body.trim().length <= EMPTY_SHELL_MAX_CHARS * 4;
  return body.trim() === "";
}
