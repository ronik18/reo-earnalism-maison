export function internalPageURL(
  href: string,
  current: string,
): URL | undefined {
  const url = new URL(href, current),
    base = new URL(current);
  if (
    url.origin !== base.origin ||
    !/^\/(en|bn)\//.test(url.pathname) ||
    /\/(sign-in|email-sign-in|sign-up|sign-out|password-reset|verify-email|independent-account|offline)(\/|$)/.test(
      url.pathname,
    ) ||
    (url.pathname === base.pathname && url.search === base.search && !!url.hash)
  )
    return;
  return url;
}
export function preservePlayer(
  currentMember: string | undefined,
  nextMember: string | undefined,
  status: number,
  contentType: string,
): boolean {
  return (
    currentMember === "true" &&
    nextMember === "true" &&
    status === 200 &&
    contentType.includes("text/html")
  );
}

export function trustedIslandModule(
  src: string,
  currentBundleURL: string,
): boolean {
  try {
    const current = new URL(currentBundleURL),
      base = new URL(".", current),
      candidate = new URL(src, current);
    const file = candidate.pathname.slice(base.pathname.length);
    return (
      candidate.origin === base.origin &&
      candidate.pathname.startsWith(base.pathname) &&
      !candidate.username &&
      !candidate.password &&
      !candidate.search &&
      !candidate.hash &&
      /^[a-z][a-z0-9-]*\.js$/i.test(file)
    );
  } catch {
    return false;
  }
}
export function sameShellBuild(
  nextShellURL: string,
  currentBundleURL: string,
): boolean {
  try {
    return (
      trustedIslandModule(nextShellURL, currentBundleURL) &&
      new URL(nextShellURL, currentBundleURL).href ===
        new URL(currentBundleURL).href
    );
  } catch {
    return false;
  }
}

export class LatestNavigation {
  private active?: AbortController;
  begin() {
    this.active?.abort();
    return (this.active = new AbortController());
  }
  current(controller: AbortController) {
    return this.active === controller && !controller.signal.aborted;
  }
  finish(controller: AbortController) {
    if (this.active === controller) this.active = undefined;
  }
}
