declare module '@novnc/novnc' {
  interface RFB extends EventTarget {
    scaleViewport: boolean;
    disconnect(): void;
  }
  type RFBConstructor = new (target: HTMLElement, url: string, options: { wsProtocols: string[] }) => RFB;
  const entry: RFBConstructor | { default: RFBConstructor };
  export default entry;
}
