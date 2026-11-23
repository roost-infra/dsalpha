declare module '@novnc/novnc' {
  interface RFB extends EventTarget {
    scaleViewport: boolean;
    disconnect(): void;
  }
  type RFBConstructor = new (target: HTMLElement, socket: WebSocket) => RFB;
  const entry: RFBConstructor | { default: RFBConstructor };
  export default entry;
}
