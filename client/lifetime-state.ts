export class IslandLifetime<Host, Root extends { unmount: () => void }> {
  readonly roots = new Map<Host, { root: Root; persistent: boolean }>();
  add(host: Host, root: Root, persistent = false) {
    this.roots.set(host, { root, persistent });
  }
  disposePage() {
    for (const [host, value] of this.roots) {
      if (value.persistent) continue;
      value.root.unmount();
      this.roots.delete(host);
    }
  }
  closePersistent(remove: (host: Host) => void) {
    for (const [host, value] of this.roots) {
      if (!value.persistent) continue;
      value.root.unmount();
      this.roots.delete(host);
      remove(host);
    }
  }
}
